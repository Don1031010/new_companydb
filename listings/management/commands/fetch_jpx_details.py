"""
Scrapes company detail pages from 東証上場会社情報サービス using Playwright.

Usage:
    # All companies in your DB
    docker compose exec web python manage.py fetch_jpx_details

    # Single company (for testing)
    docker compose exec web python manage.py fetch_jpx_details --code 7203

    # Specific market segment
    docker compose exec web python manage.py fetch_jpx_details --segment tse_prime
"""

import time
import logging
from django.core.management.base import BaseCommand
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from listings.models import Company

logger = logging.getLogger(__name__)

BASE_URL = "https://www2.jpx.co.jp/tseHpFront"
SEARCH_URL = f"{BASE_URL}/JJK010010Action.do?Show=Show"
DETAIL_ACTION = f"{BASE_URL}/JJK010020Action.do"


def parse_detail_page(page) -> dict:
    """Extract all fields from the company detail page."""

    def text(selector):
        """Safely get inner text, return empty string if not found."""
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else ""
        except Exception:
            return ""

    def table_value(label: str) -> str:
        """
        Find a table cell by its adjacent label cell text.
        JPX detail page uses <td> label / <td> value pairs.
        """
        try:
            # Find all td elements, match by text content
            tds = page.query_selector_all("table td")
            for i, td in enumerate(tds):
                if label in td.inner_text().strip():
                    # Value is usually in the next td
                    if i + 1 < len(tds):
                        return tds[i + 1].inner_text().strip()
        except Exception:
            pass
        return ""

    def has_bullet(label: str) -> bool:
        """Check if a cell contains ● (bullet = yes/flagged)."""
        val = table_value(label)
        return "●" in val

    # ── Basic info table (top grid) ──────────────────────────────────────────
    # コード / ISINコード / 市場区分 / 業種 / 決算期 / 売買単位
    # These are in a structured header table — grab by position
    header_tds = page.query_selector_all("table.JJK010020 td, table td")

    data = {
        # Top info bar
        "isin_code":              table_value("ISINコード"),
        "market_segment_text":    table_value("市場区分"),
        "industry_text":          table_value("業種"),
        "fiscal_year_end_text":   table_value("決算期"),
        "unit_shares_text":       table_value("売買単位"),

        # Main detail table
        "name_en":                table_value("英文商号"),
        "shareholder_registry_agent": table_value("株主名簿管理人"),
        "established_date_text":  table_value("設立年月日"),
        "address_ja":             table_value("本社所在地"),
        "listed_exchanges_text":  table_value("上場取引所"),
        "monthly_investment_unit":table_value("月末投資単位"),

        # Earnings & AGM schedule
        "earnings_date_q1":       table_value("第一四半期（予定）"),
        "earnings_date_q2":       table_value("第二四半期（予定）"),
        "earnings_date_q3":       table_value("第三四半期（予定）"),
        "agm_date_text":          table_value("株主総会開催日（予定）"),

        # Representative
        "representative_title":   table_value("代表者役職"),
        "representative_name":    table_value("代表者氏名"),
        "listing_date_text":      table_value("上場年月日"),

        # Share counts
        "shares_listed":          table_value("上場株式数"),
        "shares_issued":          table_value("発行済株式数"),

        # Boolean flags
        "is_securities_lending":  has_bullet("貸借銘柄"),
        "is_margin_trading":      has_bullet("信用銘柄"),
        "is_jicpa_member":        "加入有り" in table_value("財務会計基準機構への加入有無"),
        "going_concern_note":     "有り" in table_value("継続企業の前提の注記の有無"),
        "has_controlling_shareholder": "有り" in table_value("支配株主等の有無"),
        "j_iriss_registered":     "登録済" in table_value("J-IRISSの登録有無"),
    }

    return data


class Command(BaseCommand):
    help = "Scrape company detail pages from 東証上場会社情報サービス"

    def add_arguments(self, parser):
        parser.add_argument(
            "--code",
            type=str,
            help="Single stock code to fetch (for testing)",
        )
        parser.add_argument(
            "--segment",
            type=str,
            help="Filter by market segment slug (e.g. tse_prime)",
        )
        parser.add_argument(
            "--delay",
            type=float,
            default=2.0,
            help="Seconds to wait between requests (default: 2.0)",
        )
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run browser in headless mode",
        )

    def handle(self, *args, **options):
        # Build queryset
        qs = Company.objects.filter(status="active")
        if options["code"]:
            qs = qs.filter(stock_code=options["code"])
        elif options["segment"]:
            qs = qs.filter(listings__market_segment=options["segment"]).distinct()

        total = qs.count()
        self.stdout.write(f"Fetching details for {total} companies...")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=options["headless"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                locale="ja-JP",
            )
            page = context.new_page()

            # Step 1: Establish session by visiting the search page
            self.stdout.write("Establishing session...")
            page.goto(SEARCH_URL, wait_until="networkidle")

            success = 0
            errors = 0

            for i, company in enumerate(qs, 1):
                self.stdout.write(
                    f"[{i}/{total}] {company.stock_code} {company.name_ja}..."
                )
                try:
                    data = self._fetch_company(page, company.stock_code, options["delay"])
                    if data:
                        self._save_company(company, data)
                        success += 1
                        self.stdout.write(
                            self.style.SUCCESS(f"  ✓ {company.representative_name}")
                        )
                    else:
                        self.stdout.write(self.style.WARNING("  ⚠ No data returned"))
                        errors += 1

                except PWTimeout:
                    self.stdout.write(self.style.ERROR(f"  ✗ Timeout"))
                    errors += 1
                    # Re-establish session after timeout
                    page.goto(SEARCH_URL, wait_until="networkidle")

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ✗ Error: {e}"))
                    errors += 1

            browser.close()

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. ✓ {success} succeeded, ✗ {errors} failed out of {total}."
            )
        )

    def _fetch_company(self, page, stock_code: str, delay: float) -> dict:
        """Navigate to a company's detail page and extract data."""

        # Step 2: Go back to search, fill in the code, submit
        page.goto(SEARCH_URL, wait_until="networkidle")

        # Fill stock code field
        page.fill("input[name='keyword'], input[type='text']", stock_code)

        # Click search button
        page.click("input[type='submit'], button[type='submit']")
        page.wait_for_load_state("networkidle")

        # Step 3: Click the company link in results
        # Links are usually the company name or code
        link = page.query_selector(f"a:has-text('{stock_code}')")
        if not link:
            # Try finding any result link
            link = page.query_selector("table.result a, .result-list a")

        if not link:
            logger.warning(f"No result link found for {stock_code}")
            return {}

        link.click()
        page.wait_for_load_state("networkidle")

        # Step 4: Parse the detail page
        data = parse_detail_page(page)

        # Polite delay between requests
        time.sleep(delay)

        return data

    def _save_company(self, company: Company, data: dict):
        """Map scraped data back to the Company model fields."""
        from datetime import date

        def parse_date(s: str):
            """Parse Japanese date formats: 1949/05/16 or 1949年05月16日"""
            if not s or s == "-":
                return None
            try:
                s = s.strip()
                if "/" in s:
                    parts = s.split("/")
                elif "年" in s:
                    s = s.replace("年", "/").replace("月", "/").replace("日", "")
                    parts = s.split("/")
                else:
                    return None
                return date(int(parts[0]), int(parts[1]), int(parts[2]))
            except Exception:
                return None

        def parse_int(s: str):
            """Parse share counts like '12,078,283'"""
            try:
                return int(s.replace(",", "").strip())
            except Exception:
                return None

        # Update fields
        if data.get("isin_code"):
            company.isin_code = data["isin_code"]
        if data.get("name_en"):
            company.name_en = data["name_en"]
        if data.get("address_ja"):
            company.address_ja = data["address_ja"]
        if data.get("representative_name"):
            company.representative_name = data["representative_name"]
        if data.get("representative_title"):
            company.representative_title = data["representative_title"]
        if data.get("shareholder_registry_agent"):
            company.shareholder_registry_agent = data["shareholder_registry_agent"]

        # Dates
        if est := parse_date(data.get("established_date_text", "")):
            company.established_date = est

        # Share counts
        if shares := parse_int(data.get("shares_issued", "")):
            company.shares_outstanding = shares

        # Boolean flags
        company.is_securities_lending = data.get("is_securities_lending", False)
        company.is_margin_trading = data.get("is_margin_trading", False)

        company.save()

        # Update listing date on the TSE Listing record
        if listing_date := parse_date(data.get("listing_date_text", "")):
            from listings.models import Listing, StockExchange
            try:
                tse = StockExchange.objects.get(code="TSE")
                Listing.objects.filter(company=company, exchange=tse).update(
                    listing_date=listing_date
                )
            except Exception:
                pass