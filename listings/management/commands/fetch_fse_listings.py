"""
Management command: fetch_fse_listings

Scrapes the Fukuoka Stock Exchange (福岡証券取引所) listed-company pages and
upserts Company + Listing records.

Site structure
--------------
List page:  https://www.fse.or.jp/listed/list.php
  - Three sections: 本則 (main board), Q-Board, Fukuoka PRO Market
  - Each <li> has an anchor: <a href="/listed/detail.php?copid=...">name</a>
  - All three sections have detail pages (copid is URL-encoded Shift-JIS)

Detail page: https://www.fse.or.jp/listed/detail.php?copid={copid}
  - Company name in <h3 class="ttl_01 mb15">
  - First table (table_02 mb15): コード, 市場区分, 業種, 決算期 (MMDD), 売買単位
  - Second table (table_02): 設立年月日, 本社所在地, 代表者役職, 代表者氏名,
                              上場年月日, 上場株式数, URL

Page encoding: Shift-JIS

Disclosures
-----------
FSE disclosure PDF filenames are FSE-specific (e.g. 26032517714.pdf) and do NOT
match TDnet/JPX filenames.  We skip FSE disclosures and rely on fetch_tdnet_daily
to populate DisclosureRecord for all FSE-listed companies.

Usage
-----
    # Scrape all FSE companies (list + detail for everyone)
    docker compose exec web python manage.py fetch_fse_listings

    # Dry run
    docker compose exec web python manage.py fetch_fse_listings --dry-run

    # Verbose output
    docker compose exec web python manage.py fetch_fse_listings --verbose

    # Skip companies already in DB (faster re-run after partial failure)
    docker compose exec web python manage.py fetch_fse_listings --skip-existing

    # Custom delay between requests
    docker compose exec web python manage.py fetch_fse_listings --delay 1.0
"""

import logging
import os
import re
import time
from datetime import date as Date

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction

from listings.models import Company, StockExchange, Listing

logger = logging.getLogger(__name__)

FSE_BASE   = "https://www.fse.or.jp"
LIST_URL   = f"{FSE_BASE}/listed/list.php"
DETAIL_URL = f"{FSE_BASE}/listed/detail.php"

REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}

# FSE section name → Listing.market_segment value
SECTION_SEGMENT_MAP = {
    "本則":                  "fse_main",
    "Q-Board":              "fse_q_board",
    "Fukuoka PRO Market":   "fse_pro_market",
}

INDUSTRY_NAME_MAP = {
    "水産・農林業": "0050", "鉱業": "1050", "建設業": "2050",
    "食料品": "3050", "繊維製品": "3100", "パルプ・紙": "3150",
    "化学": "3200", "医薬品": "3250", "石油・石炭製品": "3300",
    "ゴム製品": "3350", "ガラス・土石製品": "3400", "鉄鋼": "3450",
    "非鉄金属": "3500", "金属製品": "3550", "機械": "3600",
    "電気機器": "3650", "輸送用機器": "3700", "精密機器": "3750",
    "その他製品": "3800", "電気・ガス業": "4050", "陸運業": "5050",
    "海運業": "5100", "空運業": "5150", "倉庫・運輸関連業": "5200",
    "情報・通信業": "5250", "卸売業": "6050", "小売業": "6100",
    "銀行業": "7050", "証券・商品先物取引業": "7100", "保険業": "7150",
    "その他金融業": "7200", "不動産業": "8050", "サービス業": "9050",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_html(session: requests.Session, url: str) -> BeautifulSoup | None:
    """Fetch a Shift-JIS page and return a BeautifulSoup tree."""
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        content = r.content.decode("shift_jis", errors="replace")
        return BeautifulSoup(content, "html.parser")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None
        logger.warning("GET %s failed: %s", url, e)
        return None
    except requests.RequestException as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def _fiscal_month(s: str) -> str:
    """
    Parse the fiscal year-end month from FSE's 決算期 field.

    Two formats appear on FSE detail pages:
      MMDD text: '0930' → '9',  '0331' → '3'
      Japanese:  '2月末' → '2',  '11月末' → '11'
    """
    s = s.strip()
    # Japanese format: "2月末", "11月末"
    m = re.match(r"^(\d{1,2})月", s)
    if m:
        return str(int(m.group(1)))
    # MMDD format
    try:
        return str(int(s[:2]))
    except (ValueError, IndexError):
        return ""


def _fiscal_day(s: str) -> int | None:
    """
    Parse the fiscal year-end day from FSE's 決算期 field.

    '0930' → 30,  '0331' → 31.
    '2月末' / '11月末' → None (last day of month — day is implicit).
    Returns None for empty/invalid input.
    """
    s = s.strip()
    # Japanese "XX月末" means last day of month
    if re.match(r"^\d{1,2}月末", s):
        return None
    # MMDD format
    try:
        day = int(s[2:4])
        return day if day > 0 else None
    except (ValueError, IndexError):
        return None


def _parse_ja_date(s: str) -> Date | None:
    """'1939年07月01日' → date(1939, 7, 1)"""
    m = re.match(r"(\d{4})年(\d{2})月(\d{2})日", s.strip())
    if m:
        try:
            return Date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _parse_shares(s: str) -> int | None:
    """'5,102,000' → 5102000"""
    try:
        return int(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


# ── List scraper ──────────────────────────────────────────────────────────────

def scrape_list(session: requests.Session) -> list[dict]:
    """
    Scrape /listed/list.php and return a list of dicts:
      { copid: str, list_name: str, section: str }

    Sections are identified by <h3 class="ttl_01 ..."> headings.
    Companies are in <ul class="list_listed_company"> that follows each heading.
    """
    soup = _get_html(session, LIST_URL)
    if soup is None:
        return []

    companies = []
    current_section = None
    main_block = soup.find("div", id="main_block") or soup

    for elem in main_block.descendants:
        if elem.name == "h3" and "ttl_01" in (elem.get("class") or []):
            span = elem.find("span")
            text = (span or elem).get_text(strip=True)
            if text in SECTION_SEGMENT_MAP:
                current_section = text
            continue

        if elem.name == "ul" and "list_listed_company" in (elem.get("class") or []):
            if current_section is None:
                continue
            for li in elem.find_all("li", recursive=False):
                a = li.find("a")
                if not a:
                    continue
                href = a.get("href", "")
                m = re.search(r"copid=([^&]+)", href)
                if m:
                    companies.append({
                        "copid":     m.group(1),
                        "list_name": a.get_text(strip=True),
                        "section":   current_section,
                    })
            # Reset so we don't re-enter for nested uls
            current_section = None

    return companies


# ── Detail scraper ────────────────────────────────────────────────────────────

def scrape_detail(session: requests.Session, copid: str) -> dict | None:
    """
    Fetch /listed/detail.php?copid={copid} and extract company data.

    Returns a dict with keys:
      stock_code, name_ja, market_section, industry, fiscal_mmdd,
      established_date, address_ja, representative_title, representative_name,
      listing_date, shares_outstanding, website
    """
    soup = _get_html(session, f"{DETAIL_URL}?copid={copid}")
    if soup is None:
        return None

    section = soup.find("section", class_="clearfix")
    if section is None:
        logger.warning("No <section class='clearfix'> found for copid=%s", copid)
        return None

    # Company name
    h3 = section.find("h3", class_="ttl_01")
    name_ja = h3.get_text(strip=True) if h3 else ""

    tables = section.find_all("table", class_="table_02")
    if not tables:
        logger.warning("No table_02 found for copid=%s", copid)
        return None

    # ── Table 1: コード, 市場区分, 業種, 決算期, 売買単位 ────────────────────────
    t1_rows = tables[0].find_all("tr")
    if len(t1_rows) < 2:
        return None
    tds = t1_rows[1].find_all("td")
    stock_code     = tds[0].get_text(strip=True) if len(tds) > 0 else ""
    market_section = tds[1].get_text(strip=True) if len(tds) > 1 else ""
    industry_text  = tds[2].get_text(strip=True) if len(tds) > 2 else ""
    fiscal_mmdd    = tds[3].get_text(strip=True) if len(tds) > 3 else ""
    unit_text      = tds[4].get_text(strip=True) if len(tds) > 4 else "100"

    # ── Table 2: 設立, 所在地, 代表者, 上場日, 株式数, URL ─────────────────────
    t2_rows = tables[1].find_all("tr") if len(tables) > 1 else []
    established = address = rep_title = rep_name = listing_date_str = shares_str = ""
    website = ""

    if len(t2_rows) >= 2:
        tds1 = t2_rows[1].find_all("td")
        established  = tds1[0].get_text(strip=True) if len(tds1) > 0 else ""
        address      = tds1[1].get_text(strip=True) if len(tds1) > 1 else ""
        rep_title    = tds1[2].get_text(strip=True) if len(tds1) > 2 else ""
        rep_name     = tds1[3].get_text(strip=True) if len(tds1) > 3 else ""

    if len(t2_rows) >= 4:
        tds2 = t2_rows[3].find_all("td")
        listing_date_str = tds2[0].get_text(strip=True) if len(tds2) > 0 else ""
        shares_str       = tds2[1].get_text(strip=True) if len(tds2) > 1 else ""
        # URL may be in a nested <a>
        if len(tds2) > 2:
            a_url = tds2[2].find("a")
            website = a_url.get("href", "").strip() if a_url else ""

    return {
        "stock_code":          stock_code,
        "name_ja":             name_ja,
        "market_section":      market_section,
        "industry":            INDUSTRY_NAME_MAP.get(industry_text, ""),
        "fiscal_mmdd":         fiscal_mmdd,
        "established_date":    _parse_ja_date(established),
        "address_ja":          address,
        "representative_title": rep_title,
        "representative_name":  rep_name,
        "listing_date":        _parse_ja_date(listing_date_str),
        "shares_outstanding":  _parse_shares(shares_str),
        "website":             website,
        "unit_shares":         _parse_shares(unit_text) or 100,
    }


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Scrape FSE listed companies and upsert Company + Listing records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Parse without writing to DB",
        )
        parser.add_argument(
            "--verbose", action="store_true",
            help="Print each company as it is processed",
        )
        parser.add_argument(
            "--skip-existing", action="store_true",
            help="Skip companies whose stock_code already exists in DB",
        )
        parser.add_argument(
            "--delay", type=float, default=REQUEST_DELAY,
            metavar="SEC",
            help=f"Seconds between detail-page requests (default: {REQUEST_DELAY})",
        )

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        try:
            fse = StockExchange.objects.get(code="FSE")
        except StockExchange.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                "FSE StockExchange record not found — "
                "add it in the admin or via a data migration first"
            ))
            return

        session = requests.Session()
        session.headers.update(HEADERS)

        # ── Step 1: collect company list from list.php ────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("=== Step 1: Fetching company list ==="))
        entries = scrape_list(session)
        self.stdout.write(f"  Found {len(entries)} companies across all sections")
        if not entries:
            self.stderr.write(self.style.ERROR("No companies found — check site structure"))
            return

        section_counts = {}
        for e in entries:
            section_counts[e["section"]] = section_counts.get(e["section"], 0) + 1
        for sec, cnt in section_counts.items():
            self.stdout.write(f"    {sec}: {cnt}")

        # ── Step 2: scrape detail pages ───────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Step 2: Scraping detail pages ==="))

        existing_codes: set[str] = set()
        if options["skip_existing"]:
            existing_codes = set(Company.objects.values_list("stock_code", flat=True))
            self.stdout.write(f"  (--skip-existing: {len(existing_codes)} codes already in DB)")

        created_co = updated_co = created_li = updated_li = errors = 0

        for i, entry in enumerate(entries, 1):
            copid   = entry["copid"]
            section = entry["section"]
            segment = SECTION_SEGMENT_MAP[section]
            label   = f"[{i}/{len(entries)}] {entry['list_name'][:30]} ({section})"

            detail = scrape_detail(session, copid)
            if detail is None:
                self.stdout.write(self.style.ERROR(f"  ERROR  {label} — detail page failed"))
                errors += 1
                time.sleep(options["delay"])
                continue

            stock_code = detail["stock_code"]
            if not stock_code:
                self.stdout.write(self.style.ERROR(
                    f"  ERROR  {label} — no stock_code found"
                ))
                errors += 1
                time.sleep(options["delay"])
                continue

            if options["skip_existing"] and stock_code in existing_codes:
                if options["verbose"]:
                    self.stdout.write(f"  skip   {stock_code}  {label}")
                time.sleep(options["delay"])
                continue

            if options["dry_run"]:
                self.stdout.write(
                    f"  [dry]  {stock_code}  {detail['name_ja'][:30]:<30}  {segment}"
                    f"  fiscal={detail['fiscal_mmdd']}"
                )
                time.sleep(options["delay"])
                continue

            c, u, cl, ul = self._save_company(detail, segment, fse, options["verbose"])
            created_co += c
            updated_co += u
            created_li += cl
            updated_li += ul

            time.sleep(options["delay"])

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Done.\n"
                f"  Companies — created: {created_co}  updated: {updated_co}\n"
                f"  Listings  — created: {created_li}  updated: {updated_li}\n"
                f"  Errors: {errors}"
            ))

    @transaction.atomic
    def _save_company(
        self,
        detail: dict,
        segment: str,
        fse: StockExchange,
        verbose: bool,
    ) -> tuple[int, int, int, int]:
        """
        Upsert Company + FSE Listing from a detail-page dict.
        Returns (co_created, co_updated, li_created, li_updated).
        """
        stock_code = detail["stock_code"]
        fm = _fiscal_month(detail["fiscal_mmdd"])
        fd = _fiscal_day(detail["fiscal_mmdd"])

        company, co_created = Company.objects.get_or_create(
            stock_code=stock_code,
            defaults={
                "name_ja":               detail["name_ja"],
                "industry_33":           detail["industry"],
                "fiscal_year_end_month": fm,
                "fiscal_year_end_day":   fd,
                "established_date":      detail["established_date"],
                "address_ja":            detail["address_ja"],
                "representative_name":   detail["representative_name"],
                "representative_title":  detail["representative_title"],
                "shares_outstanding":    detail["shares_outstanding"],
                "website":               detail["website"],
                "unit_shares":           detail["unit_shares"],
                "is_non_jpx":            True,
            },
        )

        co_updated = 0
        if not co_created and company.is_non_jpx:
            # For dual-listed companies, JPX data is authoritative; skip company fields.
            patch = {}
            if not company.name_ja and detail["name_ja"]:
                patch["name_ja"] = detail["name_ja"]
            if not company.industry_33 and detail["industry"]:
                patch["industry_33"] = detail["industry"]
            if not company.fiscal_year_end_month and fm:
                patch["fiscal_year_end_month"] = fm
            if company.fiscal_year_end_day is None and fd is not None:
                patch["fiscal_year_end_day"] = fd
            if not company.established_date and detail["established_date"]:
                patch["established_date"] = detail["established_date"]
            if not company.address_ja and detail["address_ja"]:
                patch["address_ja"] = detail["address_ja"]
            if not company.representative_name and detail["representative_name"]:
                patch["representative_name"] = detail["representative_name"]
            if not company.representative_title and detail["representative_title"]:
                patch["representative_title"] = detail["representative_title"]
            if not company.shares_outstanding and detail["shares_outstanding"]:
                patch["shares_outstanding"] = detail["shares_outstanding"]
            if not company.website and detail["website"]:
                patch["website"] = detail["website"]
            if patch:
                for f, v in patch.items():
                    setattr(company, f, v)
                company.save(update_fields=list(patch.keys()))
                co_updated = 1

        listing, li_created = Listing.objects.get_or_create(
            company=company,
            exchange=fse,
            defaults={
                "market_segment": segment,
                "listing_date":   detail["listing_date"],
                "status":         "active",
            },
        )
        li_updated = 0
        if not li_created:
            patch = {}
            if segment and listing.market_segment != segment:
                patch["market_segment"] = segment
            if detail["listing_date"] and not listing.listing_date:
                patch["listing_date"] = detail["listing_date"]
            if listing.status != "active":
                patch["status"] = "active"
            if patch:
                for f, v in patch.items():
                    setattr(listing, f, v)
                listing.save(update_fields=list(patch.keys()))
                li_updated = 1

        if verbose:
            action = "CREATE" if co_created else ("UPDATE" if co_updated else "skip")
            self.stdout.write(
                f"  [{action}] {stock_code}  {detail['name_ja'][:28]:<28}  {segment}"
            )

        return int(co_created), co_updated, int(li_created), li_updated
