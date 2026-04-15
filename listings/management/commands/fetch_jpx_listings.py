"""
Management command: fetch_jpx_listings

Scrapes 東証上場会社情報サービス in two phases:

  Phase 1 — Collect
    Submits 簡易検索 with all 市場区分 except ETF/ETN/REIT/インフラ/その他,
    sets 表示社数 to 200, paginates through every result page, and collects
    (code4, code5, name, segment, industry, fiscal_month) for every company.
    Data available from the list is saved immediately (no detail visit needed).

  Phase 2 — Detail
    For each company, searches by its 5-digit code, clicks the 基本情報 button,
    and scrapes the detail page for address, representative, dates, share counts,
    and boolean flags.

HTML facts confirmed from DevTools:
  - Submit:       <input type="button" name="searchButton" value="検索">
  - Display count: <select name="dspSsuPd"> options 10/50/100/200
  - Checkboxes:   <input name="szkbuChkbx" value="011|012|013|008|111|112|113|ETF|ETN|RET|IFD|999">
  - Result rows:  hidden inputs name="ccJjCrpSelKekkLst_st[N].eqMgrCd" (5-digit code)
                  name="ccJjCrpSelKekkLst_st[N].eqMgrNm"  (company name)
                  name="ccJjCrpSelKekkLst_st[N].szkbuNm"  (segment)
                  name="ccJjCrpSelKekkLst_st[N].gyshDspNm"(industry)
                  name="ccJjCrpSelKekkLst_st[N].dspYuKssnKi" (fiscal month)
  - Pagination:   <div class="next"><a href="javascript:setPage(N)..."><img alt="次へ"></a></div>
  - Detail btn:   <input type="button" name="detail_button" value="基本情報"
                         onclick="gotoBaseJh('13010', '1');">
  - 5-digit code: first 4 digits = stock code, 5th digit = exchange suffix (always 0 for TSE)

Usage:
    # Full run
    docker compose run --rm scraper python manage.py fetch_jpx_listings

    # Phase 1 only (collect + save list data, skip detail pages)
    docker compose run --rm scraper python manage.py fetch_jpx_listings --skip-detail

    # Test: first 5 companies, show browser window
    docker compose run --rm scraper python manage.py fetch_jpx_listings --limit 5 --no-headless

    # Headless with screenshots saved to /app/debug/
    docker compose run --rm scraper python manage.py fetch_jpx_listings --limit 5 --screenshots
"""

import os
import re
import time
import logging
import subprocess
from datetime import date as Date, datetime, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from listings.models import Company, StockExchange, Listing, DisclosureRecord

logger = logging.getLogger(__name__)

JPX_HOST   = "https://www2.jpx.co.jp"
BASE_URL   = f"{JPX_HOST}/tseHpFront"
SEARCH_URL = f"{BASE_URL}/JJK010010Action.do?Show=Show"

# Checkbox values to EXCLUDE (confirmed from DevTools)
EXCLUDE_VALUES = frozenset(["ETF", "ETN", "RET", "IFD", "999"])

# 33-industry text → model choice code  (extend as needed)
INDUSTRY_33_MAP = {v: k for k, v in [
    ("0050", "水産・農林業"), ("1050", "鉱業"), ("2050", "建設業"),
    ("3050", "食料品"), ("3100", "繊維製品"), ("3150", "パルプ・紙"),
    ("3200", "化学"), ("3250", "医薬品"), ("3300", "石油・石炭製品"),
    ("3350", "ゴム製品"), ("3400", "ガラス・土石製品"), ("3450", "鉄鋼"),
    ("3500", "非鉄金属"), ("3550", "金属製品"), ("3600", "機械"),
    ("3650", "電気機器"), ("3700", "輸送用機器"), ("3750", "精密機器"),
    ("3800", "その他製品"), ("4050", "電気・ガス業"), ("5050", "陸運業"),
    ("5100", "海運業"), ("5150", "空運業"), ("5200", "倉庫・運輸関連業"),
    ("5250", "情報・通信業"), ("6050", "卸売業"), ("6100", "小売業"),
    ("7050", "銀行業"), ("7100", "証券・商品先物取引業"), ("7150", "保険業"),
    ("7200", "その他金融業"), ("8050", "不動産業"), ("9050", "サービス業"),
]}

SEGMENT_MAP = {
    "プライム":         "tse_prime",
    "スタンダード":     "tse_standard",
    "グロース":         "tse_growth",
    "TOKYO PRO Market": "tse_pro",
    "外国株プライム":   "tse_prime",
    "外国株スタンダード": "tse_standard",
    "外国株グロース":   "tse_growth",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def hidden_values(page, name_fragment: str) -> list[str]:
    """Return .value of every hidden input whose name contains name_fragment."""
    els = page.query_selector_all(f"input[type='hidden'][name*='{name_fragment}']")
    return [(el.get_attribute("value") or "").strip() for el in els]


def table_value(page, label: str) -> str:
    """Find a <td> containing label, return the text of the next <td>."""
    try:
        tds = page.query_selector_all("td")
        for i, td in enumerate(tds):
            try:
                txt = td.inner_text().strip()
            except Exception:
                continue
            if label in txt:
                if i + 1 < len(tds):
                    try:
                        return tds[i + 1].inner_text().strip()
                    except Exception:
                        pass
    except Exception:
        pass
    return ""


def parse_date(s: str):
    if not s or s.strip() in ("-", "―", ""):
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
        return Date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def parse_int(s: str):
    try:
        return int(s.replace(",", "").strip())
    except Exception:
        return None


def parse_fiscal_month(s: str) -> str:
    """'3月' → '3',  '3月31日' → '3',  '12月31日' → '12'."""
    try:
        m = re.search(r"(\d+)月", s)
        return m.group(1) if m else ""
    except Exception:
        return ""


def start_xvfb(display: str = ":99") -> subprocess.Popen:
    proc = subprocess.Popen(
        ["Xvfb", display, "-screen", "0", "1280x900x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    os.environ["DISPLAY"] = display
    time.sleep(1)
    return proc


# ── Command ───────────────────────────────────────────────────────────────────

class Command(BaseCommand):
    help = "Scrape 東証上場会社情報サービス — 簡易検索 list + 基本情報 detail"

    def add_arguments(self, parser):
        parser.add_argument("--no-headless", action="store_true", default=False,
                            help="Show browser window (starts Xvfb automatically)")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after N companies (0 = all)")
        parser.add_argument("--delay", type=float, default=1.5,
                            help="Seconds between detail-page requests (default: 1.5)")
        parser.add_argument("--skip-detail", action="store_true", default=False,
                            help="Phase 1 only — collect list data, skip detail pages")
        parser.add_argument("--detail-only", action="store_true", default=False,
                            help="Phase 2 only — skip Phase 1, load companies from DB")
        parser.add_argument("--screenshots", action="store_true", default=False,
                            help="Save debug screenshots to /app/debug/")
        parser.add_argument("--codes", nargs="+", metavar="CODE",
                            help="Only scrape details for these stock codes (e.g. 5619 7723 9404)")
        parser.add_argument("--industry", nargs="+", metavar="INDUSTRY_33",
                            help="Only scrape details for companies in these 33-industry codes (e.g. 3650 3600)")
        parser.add_argument("--disclosure-days", type=int, default=7,
                            help="Re-scrape disclosures for companies last fetched more than N days ago (default: 7)")

    def handle(self, *args, **options):
        # Playwright's sync_api runs its own event loop; Django misidentifies
        # that as an async context and blocks ORM calls. This flag re-enables them.
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        headless = not options["no_headless"]
        self._screenshot_dir = Path("/tmp/debug") if options["screenshots"] else None
        if self._screenshot_dir:
            self._screenshot_dir.mkdir(parents=True, exist_ok=True)

        xvfb_proc = None
        if not headless:
            self.stdout.write("  Starting Xvfb virtual display...")
            try:
                xvfb_proc = start_xvfb()
            except FileNotFoundError:
                self.stderr.write(self.style.ERROR(
                    "xvfb not found. Rebuild the scraper image:\n"
                    "  docker compose --profile scraper build scraper"
                ))
                return

        try:
            self._run(headless, options)
        finally:
            if xvfb_proc:
                xvfb_proc.terminate()

    def _run(self, headless: bool, options: dict):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            ctx = browser.new_context(
                locale="ja-JP",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()
            page.set_default_timeout(30_000)

            # ── Phase 1 ───────────────────────────────────────────────────────
            if options["detail_only"]:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "\n=== Phase 1: Skipped (--detail-only) — loading from DB ==="
                ))
                entries = list(
                    Company.objects.filter(is_non_jpx=False)
                    .values("stock_code", "name_ja")
                )
                entries = [
                    {"code4": e["stock_code"], "code5": e["stock_code"] + "0", "name": e["name_ja"]}
                    for e in entries
                ]
                self.stdout.write(f"  Loaded {len(entries)} companies from DB\n")
            else:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "\n=== Phase 1: Collecting companies from 簡易検索 ==="
                ))
                entries = self._phase1_collect(page, options["limit"])
                self.stdout.write(self.style.SUCCESS(
                    f"  Total collected: {len(entries)} companies\n"
                ))

            if options["skip_detail"] or not entries:
                browser.close()
                return

            # ── Phase 2 ───────────────────────────────────────────────────────
            # Filter: only companies where details have never been scraped,
            # or where detail_scraped_at < updated_at (list data refreshed since last detail run).
            disclosure_cutoff = timezone.now() - timedelta(days=options["disclosure_days"])
            stale_qs = Company.objects.filter(
                Q(detail_scraped_at__isnull=True) |
                Q(detail_scraped_at__lt=F("updated_at")) |
                Q(disclosures_scraped_at__isnull=True) |
                Q(disclosures_scraped_at__lt=disclosure_cutoff)
            )
            if options["codes"]:
                stale_qs = stale_qs.filter(stock_code__in=options["codes"])
            if options["industry"]:
                stale_qs = stale_qs.filter(industry_33__in=options["industry"])
            stale_codes = set(stale_qs.values_list("stock_code", flat=True))
            pending = [e for e in entries if e["code4"] in stale_codes]
            skipped = len(entries) - len(pending)

            self.stdout.write(self.style.MIGRATE_HEADING(
                "=== Phase 2: Scraping 基本情報 detail pages ==="
            ))
            if skipped:
                self.stdout.write(f"  Skipping {skipped} already up-to-date companies")
            self.stdout.write(f"  {len(pending)} companies to scrape\n")

            if options["limit"]:
                pending = pending[:options["limit"]]

            ok = err = 0
            for i, entry in enumerate(pending, 1):
                code4, code5, name = entry["code4"], entry["code5"], entry["name"]
                self.stdout.write(f"[{i}/{len(pending)}] {code4}  {name}")
                try:
                    data = self._scrape_detail(page, code4, code5, options["delay"])
                    if data:
                        self._save_detail(code4, data)
                        # Page is still on the detail page — scrape 適時開示情報 tab
                        disclosures = self._scrape_disclosures(page)
                        saved_count = self._save_disclosures(code4, disclosures)
                        self.stdout.write(self.style.SUCCESS(
                            f"  ✓ saved  (適時開示: {saved_count}件)"
                        ))
                        ok += 1
                    else:
                        self.stdout.write(self.style.WARNING("  ⚠ no data"))
                        err += 1
                except PWTimeout:
                    self.stdout.write(self.style.ERROR("  ✗ timeout"))
                    err += 1
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  ✗ {e}"))
                    logger.exception(f"Error scraping detail for {code4}")
                    err += 1

            browser.close()

        self.stdout.write(self.style.SUCCESS(
            f"\nDone.  ✓ {ok} saved   ✗ {err} failed   total {len(pending)}"
        ))

    # ── Screenshot helper ─────────────────────────────────────────────────────

    def _screenshot(self, page, name: str):
        if self._screenshot_dir:
            path = self._screenshot_dir / f"{name}.png"
            page.screenshot(path=str(path), full_page=True)
            self.stdout.write(f"  📸 {path}")

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    def _extract_total_count(self, page) -> int | None:
        """
        Read the expected total from the paginator text, e.g. '1～200件を表示／3928件中'.
        Returns the integer after '／' and before '件中', or None if not found.
        """
        try:
            text = page.inner_text("body")
            m = re.search(r"／(\d[\d,]*)件中", text)
            if m:
                return int(m.group(1).replace(",", ""))
        except Exception:
            pass
        return None

    def _phase1_collect(self, page, limit: int) -> list[dict]:
        """
        Submit 簡易検索 and paginate through results.
        Returns list of dicts with code4, code5, name, segment, industry, fiscal_month.
        Also saves list-page data to the DB immediately.
        """
        self.stdout.write(f"  Loading {SEARCH_URL}")
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")
        self._screenshot(page, "01_search_form")

        self._submit_search_form(page)
        self.stdout.write(f"  After submit → {page.url}")
        self._screenshot(page, "02_results_page1")

        expected_total = self._extract_total_count(page)
        if expected_total is not None:
            self.stdout.write(f"  Paginator reports {expected_total:,} companies total")
        else:
            self.stdout.write(self.style.WARNING("  ⚠ Could not read total count from paginator"))

        entries: list[dict] = []
        page_num = 0

        while True:
            page_num += 1
            rows = self._extract_result_rows(page)
            for row in rows:
                self._save_list_data(row)
            entries.extend(rows)
            self.stdout.write(
                f"  Page {page_num}: +{len(rows)} rows  (total: {len(entries)})"
            )

            if limit and len(entries) >= limit:
                entries = entries[:limit]
                self.stdout.write(f"  Reached --limit {limit}, stopping.")
                break

            if not self._click_next_page(page):
                self.stdout.write("  No more pages.")
                break

        if expected_total is not None and not limit:
            if len(entries) == expected_total:
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ Collected {len(entries):,} companies — matches paginator total"
                ))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  ⚠ Collected {len(entries):,} companies but paginator reported {expected_total:,}"
                ))

        return entries

    def _submit_search_form(self, page):
        """
        Set 市場区分 checkboxes, 表示社数=200, click 検索.
        All selectors confirmed from DevTools.
        """
        # ── 市場区分 checkboxes (name="szkbuChkbx") ──────────────────────────
        checkboxes = page.query_selector_all("input[name='szkbuChkbx']")
        self.stdout.write(f"  Found {len(checkboxes)} 市場区分 checkbox(es)")
        for cb in checkboxes:
            val = (cb.get_attribute("value") or "").strip()
            if val in EXCLUDE_VALUES:
                cb.uncheck()
                self.stdout.write(f"    ✗ skip:  {val}")
            else:
                cb.check()
                self.stdout.write(f"    ✓ check: {val}")

        # ── 表示社数 (name="dspSsuPd") ───────────────────────────────────────
        try:
            page.select_option("select[name='dspSsuPd']", "200")
            self.stdout.write("  表示社数 → 200")
        except Exception as e:
            self.stdout.write(f"  ⚠ Could not set 表示社数: {e}")

        self._screenshot(page, "01b_form_filled")

        # ── Submit (name="searchButton", type="button") ───────────────────────
        page.click("input[name='searchButton']")
        page.wait_for_load_state("networkidle")

    def _extract_result_rows(self, page) -> list[dict]:
        """
        Read company data from hidden inputs in the results table.
        Each company has a set of hidden inputs named:
          ccJjCrpSelKekkLst_st[N].eqMgrCd   (5-digit code)
          ccJjCrpSelKekkLst_st[N].eqMgrNm   (company name)
          ccJjCrpSelKekkLst_st[N].szkbuNm   (market segment)
          ccJjCrpSelKekkLst_st[N].gyshDspNm (industry)
          ccJjCrpSelKekkLst_st[N].dspYuKssnKi (fiscal month)
        """
        entries = []
        try:
            codes    = hidden_values(page, "eqMgrCd")
            names    = hidden_values(page, "eqMgrNm")
            segments = hidden_values(page, "szkbuNm")
            industry = hidden_values(page, "gyshDspNm")
            fiscal   = hidden_values(page, "dspYuKssnKi")

            for i, code5 in enumerate(codes):
                if len(code5) != 5:
                    continue
                entries.append({
                    "code4":         code5[:4],
                    "code5":         code5,
                    "name":          names[i]    if i < len(names)    else "",
                    "segment":       segments[i] if i < len(segments) else "",
                    "industry":      industry[i] if i < len(industry) else "",
                    "fiscal_month":  fiscal[i]   if i < len(fiscal)   else "",
                })
        except Exception as e:
            logger.warning(f"Row extraction error: {e}")
        return entries

    def _click_next_page(self, page) -> bool:
        """Click the 次へ link inside <div class='next'>."""
        try:
            nxt = page.query_selector("div.next a")
            if nxt:
                with page.expect_navigation(wait_until="networkidle", timeout=30_000):
                    nxt.click()
                page.wait_for_selector("input[name*='eqMgrCd']", state="attached", timeout=15_000)
                return True
        except Exception as e:
            logger.warning(f"Pagination error: {e}")
        return False

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    def _scrape_detail(self, page, code4: str, code5: str, delay: float) -> dict:
        """
        Search for the company by its 5-digit code, then click 基本情報.
        """
        # Go to search form
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.wait_for_load_state("networkidle")

        # Fill code field (name="eqMgrCd", maxlength=5)
        page.fill("input[name='eqMgrCd']", code5)

        # Submit
        page.click("input[name='searchButton']")
        page.wait_for_load_state("networkidle")

        # Click the 基本情報 button (first one in results)
        btn = page.query_selector("input[name='detail_button']")
        if not btn:
            self.stdout.write(f"  ⚠ No 基本情報 button found for {code5}")
            time.sleep(delay)
            return {}

        btn.click()
        page.wait_for_load_state("networkidle")
        self._screenshot(page, f"detail_{code4}")

        data = self._parse_kihon_joho(page)
        time.sleep(delay)
        return data

    def _parse_kihon_joho(self, page) -> dict:
        """
        Extract 基本情報 fields from the detail page.

        Page structure (confirmed from DevTools):
          - Company name: <h3> inside <div class="boxOptListed05">
          - Data tables:  header row of <th> cells followed by a value row of <td> cells.
            Labels and values are zipped by column position.
          - Boolean flags: cell contains <strong>●</strong> when true.
        """
        # Build label→value dict from all tables
        th_map: dict[str, str] = {}
        try:
            tables = page.query_selector_all("table")
            for table in tables:
                rows = table.query_selector_all("tr")
                i = 0
                while i < len(rows):
                    ths = rows[i].query_selector_all("th")
                    if ths and i + 1 < len(rows):
                        tds = rows[i + 1].query_selector_all("td")
                        for j, th in enumerate(ths):
                            try:
                                key = th.inner_text().strip()
                                val = tds[j].inner_text().strip() if j < len(tds) else ""
                                if key:
                                    th_map[key] = val
                            except Exception:
                                pass
                        i += 2
                    else:
                        i += 1
        except Exception:
            pass

        def get(label: str) -> str:
            """Substring match on key (handles keys with embedded newlines/extra text)."""
            for k, v in th_map.items():
                if label in k:
                    return v
            return ""

        def has_bullet(label: str) -> bool:
            return "●" in get(label)

        # Company name lives in an <h3> heading, not a table cell
        name_ja = ""
        try:
            h3 = page.query_selector(".boxOptListed05 h3")
            if h3:
                name_ja = h3.inner_text().strip()
        except Exception:
            pass

        return {
            "name_ja":                  name_ja,
            "name_en":                  get("英文商号"),
            "established_date_text":    get("設立年月日"),
            "address_ja":               get("本社所在地"),
            "representative_title":     get("代表者役職"),
            "representative_name":      get("代表者氏名"),
            "listing_date_text":        get("上場年月日"),
            "fiscal_year_end_text":     get("決算期"),
            "unit_shares_text":         get("売買単位"),
            "shares_issued_text":       get("発行済株式数"),
            "is_margin_trading":        has_bullet("信用銘柄"),
            "is_securities_lending":    has_bullet("貸借銘柄"),
            # Earnings announcement dates
            "earnings_date_annual_text": get("決算発表（予定）"),
            "earnings_date_q1_text":     get("第一四半期（予定）"),
            "earnings_date_q2_text":     get("第二四半期（予定）"),
            "earnings_date_q3_text":     get("第三四半期（予定）"),
        }

    def _scrape_disclosures(self, page) -> list[dict]:
        """
        Switch to the 適時開示情報 tab (tab 2) on the current detail page and
        parse rows from both disclosure tables.

        1101 rows (・[決算情報]) are returned before 1102 rows
        (・[決定事実 / 発生事実]) so that when the same PDF appears in both tables,
        _save_disclosures keeps the richer 1101 version.

        All hidden rows (display:none) are included since Playwright sees the full DOM.
        """
        try:
            tab = page.query_selector("a:text('適時開示情報'), input[value='適時開示情報']")
            if tab:
                tab.click()
            else:
                page.evaluate("changeTab('2')")
            page.wait_for_load_state("networkidle", timeout=15_000)
            page.wait_for_selector(
                "tr[id^='1101_'], tr[id^='1102_']",
                timeout=15_000,
                state="attached",
            )
        except Exception as e:
            logger.warning("_scrape_disclosures failed: %s (url=%s)", e, page.url)
            return []

        def parse_row(row) -> dict | None:
            tds = row.query_selector_all("td")
            if len(tds) < 2:
                return None

            # Column 0: 開示日
            date_text = tds[0].inner_text().strip()
            try:
                disclosed_date = datetime.strptime(date_text, "%Y/%m/%d").date()
            except ValueError:
                return None

            # Column 1: 表題 + PDF link
            title = ""
            pdf_url = ""
            a = tds[1].query_selector("a")
            if a:
                title = a.inner_text().strip()
                href = a.get_attribute("href") or ""
                if href.startswith("/"):
                    pdf_url = JPX_HOST + href
                elif href.startswith("http"):
                    pdf_url = href

            if not pdf_url:
                return None  # no stable key — skip

            # Column 2: XBRL — onclick is on a child <img> calling doDownload(..., '/path/to.zip')
            xbrl_url = ""
            if len(tds) > 2:
                el = tds[2].query_selector("[onclick]") or tds[2]
                onclick = el.get_attribute("onclick") or ""
                m = re.search(r"'(/[^']+\.zip)'", onclick)
                if m:
                    xbrl_url = JPX_HOST + "/disc" + m.group(1)

            # Columns 3–4: HTML summary + attachment (present in 1101 rows)
            html_summary_url = ""
            html_attachment_url = ""
            if len(tds) > 3:
                a = tds[3].query_selector("a")
                if a:
                    href = a.get_attribute("href") or ""
                    if href.startswith("/"):
                        html_summary_url = JPX_HOST + href
                    elif href.startswith("http"):
                        html_summary_url = href
            if len(tds) > 4:
                a = tds[4].query_selector("a")
                if a:
                    href = a.get_attribute("href") or ""
                    if href.startswith("/"):
                        html_attachment_url = JPX_HOST + href
                    elif href.startswith("http"):
                        html_attachment_url = href

            return {
                "disclosed_date":      disclosed_date,
                "title":               title,
                "pdf_url":             pdf_url,
                "xbrl_url":            xbrl_url,
                "html_summary_url":    html_summary_url,
                "html_attachment_url": html_attachment_url,
            }

        # Process 1101 rows first so they take priority in _save_disclosures
        results = []
        for prefix in ("1101_", "1102_"):
            for row in page.query_selector_all(f"tr[id^='{prefix}']"):
                entry = parse_row(row)
                if entry:
                    results.append(entry)
        return results

    @transaction.atomic
    def _save_disclosures(self, code4: str, disclosures: list[dict]) -> int:
        """
        Insert DisclosureRecord rows for the given company. Returns count created.

        Uses get_or_create (not update_or_create) so that when the same pdf_url
        appears in both the 1101 and 1102 tables, the first-seen (1101) record
        wins and the duplicate 1102 entry is silently skipped.
        """
        if not disclosures:
            return 0
        try:
            company = Company.objects.get(stock_code=code4)
        except Company.DoesNotExist:
            return 0

        created = 0
        for d in disclosures:
            obj, was_created = DisclosureRecord.objects.get_or_create(
                company=company,
                pdf_url=d["pdf_url"],
                defaults={
                    "disclosed_date":      d["disclosed_date"],
                    "title":               d["title"],
                    "xbrl_url":            d["xbrl_url"],
                    "html_summary_url":    d["html_summary_url"],
                    "html_attachment_url": d["html_attachment_url"],
                },
            )
            if was_created:
                created += 1
            else:
                # Patch any URL fields that were empty on the existing record
                patch = {}
                for field in ("xbrl_url", "html_summary_url", "html_attachment_url"):
                    if not getattr(obj, field) and d[field]:
                        patch[field] = d[field]
                if patch:
                    for field, value in patch.items():
                        setattr(obj, field, value)
                    obj.save(update_fields=list(patch.keys()))

        company.disclosures_scraped_at = timezone.now()
        company.save(update_fields=["disclosures_scraped_at"])
        return created

    # ── Save ──────────────────────────────────────────────────────────────────

    @transaction.atomic
    def _save_list_data(self, row: dict):
        """
        Upsert Company from list-page data (Phase 1).
        Sets name, segment (via Listing), industry, fiscal month.
        """
        code4   = row["code4"]
        name    = row["name"]
        segment = SEGMENT_MAP.get(row["segment"], "")
        ind33   = INDUSTRY_33_MAP.get(row["industry"], "")
        fm      = parse_fiscal_month(row["fiscal_month"])

        company, _ = Company.objects.get_or_create(
            stock_code=code4,
            defaults={"name_ja": name},
        )
        if name:
            company.name_ja = name
        if ind33:
            company.industry_33 = ind33
        if fm:
            company.fiscal_year_end_month = fm
        company.is_non_jpx = False   # confirmed listed on JPX
        if row["segment"].startswith("外国株"):
            company.is_foreign = True
        company.save()

        # Create/update TSE Listing row if we have a segment
        if segment:
            try:
                tse = StockExchange.objects.get(code="TSE")
                Listing.objects.get_or_create(
                    company=company,
                    exchange=tse,
                    defaults={"market_segment": segment, "status": "active"},
                )
            except StockExchange.DoesNotExist:
                pass

    @transaction.atomic
    def _save_detail(self, code4: str, data: dict):
        """Update Company with detail-page data (Phase 2)."""
        try:
            company = Company.objects.get(stock_code=code4)
        except Company.DoesNotExist:
            return

        for field, key in [
            ("name_ja",              "name_ja"),
            ("name_en",              "name_en"),
            ("address_ja",           "address_ja"),
            ("representative_title", "representative_title"),
            ("representative_name",  "representative_name"),
        ]:
            if data.get(key):
                setattr(company, field, data[key])

        if est := parse_date(data.get("established_date_text", "")):
            company.established_date = est
        if shares := parse_int(data.get("shares_issued_text", "")):
            company.shares_outstanding = shares
        if unit := parse_int(data.get("unit_shares_text", "")):
            company.unit_shares = unit
        if fm := parse_fiscal_month(data.get("fiscal_year_end_text", "")):
            company.fiscal_year_end_month = fm

        company.is_margin_trading     = data.get("is_margin_trading",     company.is_margin_trading)
        company.is_securities_lending = data.get("is_securities_lending", company.is_securities_lending)
        company.detail_scraped_at     = timezone.now()

        for field, key in [
            ("earnings_date_annual", "earnings_date_annual_text"),
            ("earnings_date_q1",     "earnings_date_q1_text"),
            ("earnings_date_q2",     "earnings_date_q2_text"),
            ("earnings_date_q3",     "earnings_date_q3_text"),
        ]:
            if d := parse_date(data.get(key, "")):
                setattr(company, field, d)

        company.save()

        # Update listing date on TSE Listing
        if listing_date := parse_date(data.get("listing_date_text", "")):
            try:
                tse = StockExchange.objects.get(code="TSE")
                Listing.objects.filter(company=company, exchange=tse).update(
                    listing_date=listing_date
                )
            except StockExchange.DoesNotExist:
                pass
