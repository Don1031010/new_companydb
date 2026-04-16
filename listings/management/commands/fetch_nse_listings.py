"""
Management command: fetch_nse_listings

Fetches listed company data from the Nagoya Stock Exchange (名古屋証券取引所)
via its internal JSON API and upserts into the DB.

APIs (discovered from /assets/js/unique/search_list.js and search_detail.js):
  Phase 1 — GET https://www.nse.or.jp/api/stock/search.json
  Phase 2 — GET https://www.nse.or.jp/api/stock/view.json?stockCode={code5}

Phase 1 — List collection
  Fetches all プレミア市場 (1), メイン市場 (2), ネクスト市場 (3) companies.
  - Dual-listed with TSE: adds/updates the NSE Listing row; patches blank fields.
  - NSE-only (~59 companies): creates Company with is_non_jpx=True + NSE Listing.

Phase 2 — Detail scrape (--detail flag, NSE-only companies by default)
  Calls view.json for each NSE-only company and populates:
    representative name/title, address, established date, listing date,
    shares outstanding, margin/lending flags, fiscal_year_end_day.
  Also upserts recent disclosure records (timely) into DisclosureRecord using
  pdf_filename as the deduplication key (same filename as TDnet/JPX).

Usage
-----
    # Phase 1 only
    docker compose exec web python manage.py fetch_nse_listings

    # Phase 1 + Phase 2 (detail for NSE-only companies)
    docker compose exec web python manage.py fetch_nse_listings --detail

    # Phase 2 only (skip Phase 1, use existing DB companies)
    docker compose exec web python manage.py fetch_nse_listings --detail-only

    # All NSE companies in Phase 2, not just NSE-only
    docker compose exec web python manage.py fetch_nse_listings --detail --all

    docker compose exec web python manage.py fetch_nse_listings --dry-run
    docker compose exec web python manage.py fetch_nse_listings --verbose
"""

import logging
import os
import time
from datetime import date as Date

import requests
from django.core.management.base import BaseCommand
from django.db import transaction

from listings.models import Company, StockExchange, Listing, DisclosureRecord

logger = logging.getLogger(__name__)

NSE_SEARCH_API = "https://www.nse.or.jp/api/stock/search.json"
NSE_VIEW_API   = "https://www.nse.or.jp/api/stock/view.json"
NSE_FILES_BASE = "https://www.nse.or.jp/listing/search/files"

DIVISION_SEGMENT_MAP = {
    1: "nse_premier",
    2: "nse_main",
    3: "nse_next",
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

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nse.or.jp/listing/search/",
}

REQUEST_DELAY = 0.5


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fiscal_month(accounting_term: str) -> str:
    """'1130' → '11',  '0331' → '3'"""
    try:
        return str(int(accounting_term[:2]))
    except (ValueError, IndexError):
        return ""


def _fiscal_day(accounting_term: str) -> int | None:
    """
    '0331' → 31,  '0330' → 30,  '0399' → None (末日 = last day of month).
    Returns None when day is '99' (= month-end).
    """
    try:
        day = int(accounting_term[2:4])
        return None if day == 99 else day
    except (ValueError, IndexError):
        return None


def _parse_date(s: str) -> Date | None:
    """'19730402' → date(1973, 4, 2),  None/'' → None."""
    if not s:
        return None
    try:
        return Date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError):
        return None


def _parse_shares(s: str) -> int | None:
    """'4,060,360' → 4060360"""
    try:
        return int(str(s).replace(",", ""))
    except (ValueError, TypeError):
        return None


def _get(session: requests.Session, url: str, **kwargs) -> dict | None:
    try:
        r = session.get(url, timeout=20, **kwargs)
        r.raise_for_status()
        r.encoding = "utf-8"
        return r.json()
    except Exception as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Fetch NSE listed companies and upsert Company + Listing records"

    def add_arguments(self, parser):
        parser.add_argument("--detail", action="store_true",
                            help="Phase 2: scrape detail + disclosures for NSE-only companies")
        parser.add_argument("--detail-only", action="store_true",
                            help="Skip Phase 1; run Phase 2 only")
        parser.add_argument("--all", action="store_true",
                            help="Phase 2 for ALL NSE companies, not just NSE-only")
        parser.add_argument("--dry-run", action="store_true",
                            help="Parse without writing to DB")
        parser.add_argument("--verbose", action="store_true",
                            help="Print every company processed")
        parser.add_argument("--delay", type=float, default=REQUEST_DELAY,
                            help=f"Seconds between Phase 2 requests (default: {REQUEST_DELAY})")

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        try:
            nse = StockExchange.objects.get(code="NSE")
        except StockExchange.DoesNotExist:
            self.stderr.write(self.style.ERROR(
                "NSE StockExchange record not found — run migrations first"
            ))
            return

        session = requests.Session()
        session.headers.update(HEADERS)

        # ── Phase 1 ───────────────────────────────────────────────────────────
        if not options["detail_only"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\n=== Phase 1: NSE company list ==="))
            items = self._fetch_list(session, options["verbose"])
            self.stdout.write(f"Fetched {len(items)} companies from NSE search API")

            if options["dry_run"]:
                for item in items:
                    code = item["stockCode"][:4]
                    seg  = DIVISION_SEGMENT_MAP.get(item["listedDivision"], "")
                    self.stdout.write(f"  {code}  {item['stockName_j'][:30]:<30}  {seg}")
            else:
                created_co = updated_co = created_li = updated_li = 0
                for item in items:
                    c, u, cl, ul = self._save_list_item(item, nse, options["verbose"])
                    created_co += c; updated_co += u
                    created_li += cl; updated_li += ul
                self.stdout.write(self.style.SUCCESS(
                    f"  Companies — created: {created_co}  updated: {updated_co}\n"
                    f"  Listings  — created: {created_li}  updated: {updated_li}"
                ))

        # ── Phase 2 ───────────────────────────────────────────────────────────
        if options["detail"] or options["detail_only"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\n=== Phase 2: Detail + disclosures ==="))

            if options["all"]:
                # All companies with an NSE listing
                companies = list(
                    Company.objects.filter(listings__exchange=nse)
                    .prefetch_related("listings")
                )
            else:
                # NSE-only companies
                companies = list(Company.objects.filter(is_non_jpx=True))

            self.stdout.write(f"  {len(companies)} companies to process")

            ok = err = disc_created = disc_updated = 0
            for i, company in enumerate(companies, 1):
                # Derive the 5-digit code from the NSE listing
                code4 = company.stock_code
                code5 = code4 + "0"   # NSE uses code4 + "0" suffix
                label = f"[{i}/{len(companies)}] {code4} {company.name_ja[:24]}"

                if options["verbose"]:
                    self.stdout.write(label)

                data = _get(session, NSE_VIEW_API, params={"stockCode": code5})
                if not data:
                    self.stdout.write(self.style.ERROR(f"  {label} — API error"))
                    err += 1
                    time.sleep(options["delay"])
                    continue

                if not options["dry_run"]:
                    dc, du = self._save_detail(company, nse, data, options["verbose"])
                    disc_created += dc
                    disc_updated += du
                elif options["verbose"]:
                    stock = (data.get("stock") or [{}])[0]
                    self.stdout.write(
                        f"    rep={stock.get('representativeName')}  "
                        f"listed={stock.get('listedDate')}  "
                        f"shares={stock.get('listedCount')}  "
                        f"timely={len(data.get('timely', []))}"
                    )

                ok += 1
                time.sleep(options["delay"])

            if not options["dry_run"]:
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {ok} processed   ✗ {err} errors\n"
                    f"  Disclosures — created: {disc_created}  updated: {disc_updated}"
                ))

    # ── Phase 1 helpers ───────────────────────────────────────────────────────

    def _fetch_list(self, session: requests.Session, verbose: bool) -> list[dict]:
        all_items: list[dict] = []
        page = 1
        while True:
            params = {
                "stockCode": "", "stockName_j": "",
                "listedDivision[]": ["1", "2", "3"],
                "listedSingle": "", "industryCode": "",
                "listedClose": "", "tradingUnit": "",
                "dispType": "stockCode", "dispOrder": "ASC",
                "dispCount": "100", "dispPage": str(page),
            }
            data = _get(session, NSE_SEARCH_API, params=params)
            if not data:
                break
            items = data.get("stock", [])
            if not items:
                break
            all_items.extend(items)
            meta  = data.get("list", [{}])[0]
            total = int(meta.get("listTotal", 0))
            if verbose:
                self.stdout.write(f"  Page {page}: +{len(items)}  (total: {len(all_items)}/{total})")
            if len(all_items) >= total:
                break
            page += 1
            time.sleep(REQUEST_DELAY)
        return all_items

    @transaction.atomic
    def _save_list_item(
        self, item: dict, nse: StockExchange, verbose: bool
    ) -> tuple[int, int, int, int]:
        stock_code = item["stockCode"][:4]
        name_ja    = item.get("stockName_j", "")
        name_en    = item.get("stockName_e", "")
        segment    = DIVISION_SEGMENT_MAP.get(item.get("listedDivision"), "")
        industry   = INDUSTRY_NAME_MAP.get(item.get("industryName_j", ""), "")
        term       = item.get("accountingTerm", "")
        fm         = _fiscal_month(term)
        fd         = _fiscal_day(term)

        company, co_created = Company.objects.get_or_create(
            stock_code=stock_code,
            defaults={
                "name_ja": name_ja, "name_en": name_en,
                "industry_33": industry,
                "fiscal_year_end_month": fm,
                "fiscal_year_end_day": fd,
                "is_non_jpx": True,
            },
        )

        co_updated = 0
        if not co_created:
            patch = {}
            if not company.name_en and name_en:
                patch["name_en"] = name_en
            if not company.industry_33 and industry:
                patch["industry_33"] = industry
            if not company.fiscal_year_end_month and fm:
                patch["fiscal_year_end_month"] = fm
            if company.fiscal_year_end_day is None and fd is not None:
                patch["fiscal_year_end_day"] = fd
            if patch:
                for f, v in patch.items():
                    setattr(company, f, v)
                company.save(update_fields=list(patch.keys()))
                co_updated = 1

        listing, li_created = Listing.objects.get_or_create(
            company=company, exchange=nse,
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
            self.stdout.write(f"  [{action}] {stock_code}  {name_ja[:28]:<28}  {segment}")

        return int(co_created), co_updated, int(li_created), li_updated

    # ── Phase 2 helpers ───────────────────────────────────────────────────────

    @transaction.atomic
    def _save_detail(
        self, company: Company, nse: StockExchange, data: dict, verbose: bool
    ) -> tuple[int, int]:
        """
        Update Company with detail fields and upsert DisclosureRecords from timely.
        Returns (disclosures_created, disclosures_updated).
        """
        stock = (data.get("stock") or [{}])[0]

        # ── Company detail fields ─────────────────────────────────────────────
        patch = {}
        if rep_name := stock.get("representativeName"):
            patch["representative_name"] = rep_name
        if rep_title := stock.get("representativeTitle"):
            patch["representative_title"] = rep_title
        if location := stock.get("location"):
            patch["address_ja"] = location
        if est := _parse_date(stock.get("buildDate")):
            patch["established_date"] = est
        if shares := _parse_shares(stock.get("listedCount")):
            patch["shares_outstanding"] = shares
        if stock.get("marginableStock") is not None:
            patch["is_margin_trading"] = bool(stock["marginableStock"])
        if stock.get("loanableStock") is not None:
            patch["is_securities_lending"] = bool(stock["loanableStock"])
        # fiscal_year_end_day (overwrite with fresh value from detail API)
        term = stock.get("accountingTerm", "")
        if term:
            if fm := _fiscal_month(term):
                patch["fiscal_year_end_month"] = fm
            patch["fiscal_year_end_day"] = _fiscal_day(term)

        if patch:
            for f, v in patch.items():
                setattr(company, f, v)
            company.save(update_fields=list(patch.keys()))

        # Update NSE listing date
        if listed_date := _parse_date(stock.get("listedDate")):
            Listing.objects.filter(company=company, exchange=nse).update(
                listing_date=listed_date
            )

        if verbose:
            self.stdout.write(
                f"    rep={stock.get('representativeName')}  "
                f"listed={stock.get('listedDate')}  "
                f"shares={stock.get('listedCount')}"
            )

        # ── Disclosures (timely) ──────────────────────────────────────────────
        disc_created = disc_updated = 0
        for t in data.get("timely", []):
            filename = t.get("filename", "")
            if not filename or not filename.endswith(".pdf"):
                continue
            title     = t.get("title", "")
            date_str  = t.get("date", "")
            try:
                disclosed_date = Date.fromisoformat(date_str)
            except (ValueError, TypeError):
                continue

            pdf_url = f"{NSE_FILES_BASE}/{filename}"

            obj, was_created = DisclosureRecord.objects.get_or_create(
                company=company,
                pdf_filename=filename,
                defaults={
                    "disclosed_date": disclosed_date,
                    "title":          title,
                    "pdf_url":        pdf_url,
                },
            )
            if was_created:
                disc_created += 1
            else:
                # Patch missing fields; don't overwrite a permanent JPX URL
                p = {}
                if not obj.pdf_url:
                    p["pdf_url"] = pdf_url
                if not obj.title and title:
                    p["title"] = title
                if p:
                    for f, v in p.items():
                        setattr(obj, f, v)
                    obj.save(update_fields=list(p.keys()))
                    disc_updated += 1

        return disc_created, disc_updated
