"""
Management command: fetch_sse_listings

Scrapes the Sapporo Stock Exchange (札幌証券取引所) listed-company pages and
upserts Company + Listing records.

Site structure
--------------
List page:  https://www.sse.or.jp/listing/list

Companies are grouped into <div class="catlist"> sections identified by id:
  cat01–cat21, cat23  → 本則市場    (sse_main)
  cat22               → アンビシャス市場  (sse_ambitious)
  cat24               → Sapporo PRO Frontier Market (sse_frontier)

Within each catlist div:
  <h3>{industry or market name}</h3>
  <dl class="listhead">…</dl>           ← header row, skip
  <dl>
    <dt><a href="./company{slug}" [class="tandoku"]>
          <span>{code}</span>{company name}
        </a></dt>
    <dd>…recent disclosure…</dd>
  </dl>

class="tandoku" on the anchor indicates the company is 単独上場 (SSE-only,
not dual-listed with TSE) → create Company with is_non_jpx=True.

Bond market exclusion
---------------------
北海道ESGプロボンドマーケット (bond listings) does NOT appear on /listing/list
at all — it has its own separate section on the site.  No filtering is needed.

Detail pages (optional --detail flag)
--------------------------------------
URL:  https://www.sse.or.jp/listing/company{slug}
Provides: address_ja, website.
(No fiscal year end, listing date, or representative data available.)
Useful mainly for SSE-only companies that aren't populated by fetch_jpx_listings.

Usage
-----
    # Phase 1 only — list page, all 68 companies
    docker compose exec web python manage.py fetch_sse_listings

    # Phase 1 + address/website for SSE-only companies
    docker compose exec web python manage.py fetch_sse_listings --detail

    # Detail for ALL SSE companies, not just SSE-only
    docker compose exec web python manage.py fetch_sse_listings --detail --all

    docker compose exec web python manage.py fetch_sse_listings --dry-run --verbose
"""

import logging
import os
import re
import time

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction

from listings.models import Company, StockExchange, Listing

logger = logging.getLogger(__name__)

SSE_BASE     = "https://www.sse.or.jp"
LIST_URL     = f"{SSE_BASE}/listing/list"
DETAIL_BASE  = f"{SSE_BASE}/listing/company"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# cat id ranges → segment
# cat01–cat21, cat23 = 本則市場 industry sections
# cat22 = アンビシャス市場
# cat24 = Sapporo PRO Frontier Market
_AMBITIOUS_ID   = "cat22"
_PRO_ID         = "cat24"

INDUSTRY_NAME_MAP = {
    "建設業":       "2050",
    "食料品":       "3050",
    "パルプ紙":     "3150",
    "化学":         "3200",
    "医薬品":       "3250",
    "硝子・土石製品": "3400",
    "鉄鋼":         "3450",
    "金属製品":     "3550",
    "機械":         "3600",
    "電気機器":     "3650",
    "電気・ガス業": "4050",
    "陸運業":       "5050",
    "海運業":       "5100",
    "情報・通信業": "5250",
    "卸売業":       "6050",
    "小売業":       "6100",
    "銀行業":       "7050",
    "保険業":       "7150",
    "その他金融業": "7200",
    "不動産業":     "8050",
    "サービス業":   "9050",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        logger.warning("GET %s failed: %s", url, e)
        return None
    except requests.RequestException as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


# ── List scraper ──────────────────────────────────────────────────────────────

def scrape_list(session: requests.Session) -> list[dict]:
    """
    Scrape /listing/list and return a list of dicts:
      { stock_code, name_ja, market_segment, industry_33, is_tandoku, detail_slug }

    Industry sections are elements with id matching "cat\\d+" (section or div):
      cat22 → sse_ambitious, cat24 → sse_frontier, all others → sse_main.
    Industry (for sse_main) comes from the <h3> inside each section.
    """
    soup = _get(session, LIST_URL)
    if soup is None:
        return []

    companies = []

    # Match both <section id="catXX"> and <div class="catlist" id="catXX">
    cat_elements = soup.find_all(id=re.compile(r"^cat\d+"))

    for elem in cat_elements:
        cat_id = elem.get("id", "")
        if cat_id == _AMBITIOUS_ID:
            segment = "sse_ambitious"
        elif cat_id == _PRO_ID:
            segment = "sse_frontier"
        else:
            segment = "sse_main"

        # Industry from h3 (meaningful only for sse_main)
        h3 = elem.find("h3")
        industry_text = h3.get_text(strip=True) if h3 else ""
        industry_33 = INDUSTRY_NAME_MAP.get(industry_text, "")

        for dl in elem.find_all("dl"):
            if "listhead" in (dl.get("class") or []):
                continue
            dt = dl.find("dt")
            if not dt:
                continue
            a = dt.find("a")
            span = dt.find("span")
            if not (a and span):
                continue

            code = span.get_text(strip=True)
            # Name is the anchor text minus the code prefix
            full_text = a.get_text(strip=True)
            name_ja = full_text[len(code):].strip()
            is_tandoku = "tandoku" in (a.get("class") or [])

            # Detail page slug from href (e.g. "./company1449" or "./company353A-2")
            href = a.get("href", "")
            slug_match = re.search(r"company([^/\"'?]+)", href)
            detail_slug = slug_match.group(1) if slug_match else code

            companies.append({
                "stock_code":    code,
                "name_ja":       name_ja,
                "market_segment": segment,
                "industry_33":   industry_33,
                "is_tandoku":    is_tandoku,
                "detail_slug":   detail_slug,
            })

    return companies


# ── Detail scraper ────────────────────────────────────────────────────────────

def scrape_detail(session: requests.Session, slug: str) -> dict | None:
    """
    Fetch /listing/company{slug} and extract address_ja and website.

    The companyprofile section contains:
      <span>{code}</span> <span>{industry}</span>
      <p>{address}<br><a href="{website}">…</a></p>
    """
    url = f"{DETAIL_BASE}{slug}"
    soup = _get(session, url)
    if soup is None:
        return None

    contents = soup.find("div", class_="contents")
    if not contents:
        return None

    section = contents.find("section", id="companyprofile")
    if not section:
        return None

    p = section.find("p")
    if not p:
        return {"address_ja": "", "website": ""}

    # Website is in the <a> tag
    a_url = p.find("a")
    website = a_url.get("href", "").strip() if a_url else ""

    # Address: all text in <p> before the <a>
    address_parts = []
    for node in p.children:
        if hasattr(node, "name"):
            if node.name == "a":
                break
            if node.name == "br":
                continue
        else:
            text = str(node).strip()
            if text:
                address_parts.append(text)
    address_ja = "".join(address_parts).strip()

    return {"address_ja": address_ja, "website": website}


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Scrape SSE listed companies and upsert Company + Listing records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--detail", action="store_true",
            help="Also scrape detail pages for address/website (SSE-only companies by default)",
        )
        parser.add_argument(
            "--all", action="store_true",
            help="With --detail: scrape detail pages for ALL SSE companies, not just SSE-only",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse without writing to DB",
        )
        parser.add_argument(
            "--verbose", action="store_true",
            help="Show each company as it is processed",
        )
        parser.add_argument(
            "--delay", type=float, default=REQUEST_DELAY,
            metavar="SEC",
            help=f"Seconds between detail-page requests (default: {REQUEST_DELAY})",
        )

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        try:
            sse = StockExchange.objects.get(code="SSE")
        except StockExchange.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                "SSE StockExchange record not found — add it in the admin first"
            ))
            return

        session = requests.Session()
        session.headers.update(HEADERS)

        # ── Phase 1: list page ────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("=== Phase 1: company list ==="))
        entries = scrape_list(session)
        if not entries:
            self.stderr.write(self.style.ERROR("No companies found — check site structure"))
            return

        by_segment = {}
        tandoku_count = 0
        for e in entries:
            by_segment[e["market_segment"]] = by_segment.get(e["market_segment"], 0) + 1
            if e["is_tandoku"]:
                tandoku_count += 1
        self.stdout.write(f"  Found {len(entries)} companies")
        for seg, cnt in sorted(by_segment.items()):
            self.stdout.write(f"    {seg}: {cnt}")
        self.stdout.write(f"  単独上場 (SSE-only): {tandoku_count}")

        if options["dry_run"]:
            for e in entries:
                tandoku_mark = " [単独]" if e["is_tandoku"] else ""
                self.stdout.write(
                    f"  [dry]  {e['stock_code']}  {e['name_ja'][:30]:<30}"
                    f"  {e['market_segment']}{tandoku_mark}"
                )
        else:
            created_co = updated_co = created_li = updated_li = 0
            for e in entries:
                c, u, cl, ul = self._save_list_item(e, sse, options["verbose"])
                created_co += c; updated_co += u
                created_li += cl; updated_li += ul
            self.stdout.write(self.style.SUCCESS(
                f"  Companies — created: {created_co}  updated: {updated_co}\n"
                f"  Listings  — created: {created_li}  updated: {updated_li}"
            ))

        # ── Phase 2: detail pages (optional) ─────────────────────────────────
        if not options["detail"]:
            return

        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Phase 2: detail pages ==="))

        if options["all"]:
            targets = entries
        else:
            targets = [e for e in entries if e["is_tandoku"]]

        self.stdout.write(f"  {len(targets)} companies to scrape")

        ok = err = 0
        for i, entry in enumerate(targets, 1):
            code  = entry["stock_code"]
            slug  = entry["detail_slug"]
            label = f"[{i}/{len(targets)}] {code} {entry['name_ja'][:24]}"

            detail = scrape_detail(session, slug)
            if detail is None:
                self.stdout.write(self.style.ERROR(f"  ERROR  {label}"))
                err += 1
                time.sleep(options["delay"])
                continue

            if options["verbose"]:
                self.stdout.write(
                    f"  {code}  addr={detail['address_ja'][:40]}  web={detail['website'][:40]}"
                )

            if not options["dry_run"]:
                self._patch_detail(code, detail)
                ok += 1

            time.sleep(options["delay"])

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ {ok} updated   ✗ {err} errors"
            ))

    # ── Helpers ───────────────────────────────────────────────────────────────

    @transaction.atomic
    def _save_list_item(
        self, entry: dict, sse: StockExchange, verbose: bool
    ) -> tuple[int, int, int, int]:
        """Upsert Company + SSE Listing. Returns (co_created, co_updated, li_created, li_updated)."""
        stock_code = entry["stock_code"]
        segment    = entry["market_segment"]
        industry   = entry["industry_33"]

        company, co_created = Company.objects.get_or_create(
            stock_code=stock_code,
            defaults={
                "name_ja":    entry["name_ja"],
                "industry_33": industry,
                "is_non_jpx": True,
            },
        )

        co_updated = 0
        if not co_created:
            patch = {}
            if not company.name_ja and entry["name_ja"]:
                patch["name_ja"] = entry["name_ja"]
            if not company.industry_33 and industry:
                patch["industry_33"] = industry
            if patch:
                for f, v in patch.items():
                    setattr(company, f, v)
                company.save(update_fields=list(patch.keys()))
                co_updated = 1

        listing, li_created = Listing.objects.get_or_create(
            company=company,
            exchange=sse,
            defaults={"market_segment": segment, "status": "active"},
        )
        li_updated = 0
        if not li_created:
            patch = {}
            if segment and listing.market_segment != segment:
                patch["market_segment"] = segment
            if listing.status != "active":
                patch["status"] = "active"
            if patch:
                for f, v in patch.items():
                    setattr(listing, f, v)
                listing.save(update_fields=list(patch.keys()))
                li_updated = 1

        if verbose:
            action = "CREATE" if co_created else ("UPDATE" if co_updated else "skip")
            tandoku = " [単独]" if entry["is_tandoku"] else ""
            self.stdout.write(
                f"  [{action}] {stock_code}  {entry['name_ja'][:28]:<28}  {segment}{tandoku}"
            )

        return int(co_created), co_updated, int(li_created), li_updated

    @transaction.atomic
    def _patch_detail(self, stock_code: str, detail: dict) -> None:
        """Patch address_ja and website on an existing Company."""
        try:
            company = Company.objects.get(stock_code=stock_code)
        except Company.DoesNotExist:
            return
        patch = {}
        if not company.address_ja and detail.get("address_ja"):
            patch["address_ja"] = detail["address_ja"]
        if not company.website and detail.get("website"):
            patch["website"] = detail["website"]
        if patch:
            for f, v in patch.items():
                setattr(company, f, v)
            company.save(update_fields=list(patch.keys()))
