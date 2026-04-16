"""
Management command: fetch_tdnet_daily

Scrapes TDnet (東証適時開示情報伝達システム) for the daily disclosure feed and
inserts matching entries into DisclosureRecord for companies already in the DB.

TDnet URL structure (confirmed from HTML source)
-------------------------------------------------
Disclosures are rendered inside an iframe:
  https://www.release.tdnet.info/inbs/I_list_{page:03d}_{YYYYMMDD}.html

e.g. page 1 of today:  I_list_001_20260416.html
     page 2 of today:  I_list_002_20260416.html
     page 1 yesterday: I_list_001_20260415.html

Each page shows up to 100 rows.  We increment the page number until a page
returns no data rows.

Table structure (id="main-list-table"):
  col 0: 時刻   HH:MM
  col 1: コード 5-char code (first 4 = stock code used in our DB)
  col 2: 会社名
  col 3: 表題   — <a href="140120260416505389.pdf">title</a>   (relative filename)
  col 4: XBRL   — <a href="081220260415504781.zip">XBRL</a>   (relative filename, may be blank)
  col 5: 上場取引所
  col 6: 更新履歴

PDF URLs:  https://www.release.tdnet.info/inbs/{filename}
           These are temporary (~1 month); fetch_jpx_listings overwrites
           pdf_url with the permanent JPX URL when it next runs.

DisclosureRecord deduplication key: (company, pdf_filename)
  pdf_filename is the bare filename (e.g. 140120260416505389.pdf),
  which is identical between TDnet and JPX.

Usage
-----
    # Today only (default)
    docker compose run --rm scraper python manage.py fetch_tdnet_daily

    # Back-fill last 7 days
    docker compose run --rm scraper python manage.py fetch_tdnet_daily --days 7

    # Specific date
    docker compose run --rm scraper python manage.py fetch_tdnet_daily --date 2026-04-15

    # Dry run (parse but don't save)
    docker compose run --rm scraper python manage.py fetch_tdnet_daily --dry-run

    # Verbose (show every row including skipped)
    docker compose run --rm scraper python manage.py fetch_tdnet_daily --verbose
"""

import os
import logging
import re
import time
from datetime import date as Date, datetime, timedelta

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.db import transaction

from listings.models import Company, DisclosureRecord

logger = logging.getLogger(__name__)

TDNET_INBS = "https://www.release.tdnet.info/inbs"

# Seconds between HTTP requests
REQUEST_DELAY = 0.5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def _list_url(date: Date, page: int) -> str:
    return f"{TDNET_INBS}/I_list_{page:03d}_{date.strftime('%Y%m%d')}.html"


def _get(session: requests.Session, url: str) -> BeautifulSoup | None:
    try:
        r = session.get(url, timeout=20)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return None  # no more pages
        logger.warning("GET %s failed: %s", url, e)
        return None
    except requests.RequestException as e:
        logger.warning("GET %s failed: %s", url, e)
        return None


def _parse_page(soup: BeautifulSoup) -> list[dict]:
    """
    Extract disclosure rows from one I_list_NNN_YYYYMMDD.html page.

    Targets <table id="main-list-table"> whose data rows have 7 columns:
      [0] time  [1] 5-char code  [2] name  [3] title+PDF  [4] XBRL  [5] exchange  [6] history
    """
    table = soup.find("table", id="main-list-table")
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue

        # col 0: time — validate it looks like HH:MM
        time_text = tds[0].get_text(strip=True)
        if not re.match(r"^\d{2}:\d{2}$", time_text):
            continue

        # col 1: 5-char code; first 4 chars = stock code in our DB
        code5 = tds[1].get_text(strip=True)
        if len(code5) != 5:
            continue
        stock_code = code5[:4]

        # col 3: title + PDF link (href is a bare filename, no leading slash)
        a_pdf = tds[3].find("a")
        if not a_pdf:
            continue
        title = a_pdf.get_text(strip=True)
        pdf_filename = a_pdf.get("href", "").strip()
        if not pdf_filename or not pdf_filename.endswith(".pdf"):
            continue
        pdf_url = f"{TDNET_INBS}/{pdf_filename}"

        # col 4: XBRL zip (optional)
        xbrl_url = ""
        a_xbrl = tds[4].find("a")
        if a_xbrl:
            xbrl_href = a_xbrl.get("href", "").strip()
            if xbrl_href:
                xbrl_url = f"{TDNET_INBS}/{xbrl_href}"

        rows.append({
            "stock_code":   stock_code,
            "title":        title,
            "pdf_filename": pdf_filename,
            "pdf_url":      pdf_url,
            "xbrl_url":     xbrl_url,
        })

    return rows


class Command(BaseCommand):
    help = "Scrape TDnet daily disclosure feed and upsert DisclosureRecord rows"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "--date",
            metavar="YYYY-MM-DD",
            help="Fetch disclosures for a specific date (default: today)",
        )
        group.add_argument(
            "--days",
            type=int,
            default=1,
            metavar="N",
            help="Fetch disclosures for the last N days including today (default: 1)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and print results without writing to DB",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show every row, including skipped (company not in DB)",
        )

    def handle(self, *args, **options):
        os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

        if options["date"]:
            try:
                dates = [datetime.strptime(options["date"], "%Y-%m-%d").date()]
            except ValueError:
                self.stderr.write(self.style.ERROR(
                    f"Invalid date '{options['date']}' — use YYYY-MM-DD"
                ))
                return
        else:
            today = Date.today()
            dates = [today - timedelta(days=i) for i in range(options["days"])]

        known_codes = set(Company.objects.values_list("stock_code", flat=True))
        self.stdout.write(f"Known companies in DB: {len(known_codes)}")

        session = requests.Session()
        session.headers.update(HEADERS)

        total_created = total_updated = total_skipped = 0

        for target_date in dates:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {target_date} ==="))
            rows = self._scrape_day(session, target_date, options["verbose"])
            self.stdout.write(f"  Parsed {len(rows)} rows total")

            created = updated = skipped = 0
            for row in rows:
                if row["stock_code"] not in known_codes:
                    if options["verbose"]:
                        self.stdout.write(
                            f"  skip {row['stock_code']} {row['title'][:50]} (not in DB)"
                        )
                    skipped += 1
                    continue

                if options["dry_run"]:
                    self.stdout.write(
                        f"  [dry-run] {row['stock_code']} {row['pdf_filename']}  {row['title'][:60]}"
                    )
                    continue

                c, u = self._save_row(row, target_date)
                created += c
                updated += u

            if not options["dry_run"]:
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ created: {created}  updated: {updated}  "
                    f"skipped (not in DB): {skipped}"
                ))
            total_created += created
            total_updated += updated
            total_skipped += skipped

        if not options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"\nDone.  total created: {total_created}  "
                f"updated: {total_updated}  skipped: {total_skipped}"
            ))

    def _scrape_day(
        self, session: requests.Session, target_date: Date, verbose: bool
    ) -> list[dict]:
        all_rows: list[dict] = []
        page = 1
        while True:
            url = _list_url(target_date, page)
            if verbose:
                self.stdout.write(f"  Fetching page {page}: {url}")

            soup = _get(session, url)
            if soup is None:
                break  # 404 or error — no more pages

            rows = _parse_page(soup)
            if not rows:
                break  # empty page — done

            all_rows.extend(rows)
            if verbose:
                self.stdout.write(f"    → {len(rows)} rows (running total: {len(all_rows)})")

            page += 1
            time.sleep(REQUEST_DELAY)

        return all_rows

    @transaction.atomic
    def _save_row(self, row: dict, disclosed_date: Date) -> tuple[int, int]:
        """
        Upsert one DisclosureRecord by (company, pdf_filename).
        Returns (created, updated).

        On create:  store the TDnet pdf_url (temporary).
        On update:  patch xbrl_url if blank; leave pdf_url alone if already
                    a permanent JPX URL (jpx.co.jp), otherwise leave it too
                    — fetch_jpx_listings will overwrite with the permanent URL.
        """
        try:
            company = Company.objects.get(stock_code=row["stock_code"])
        except Company.DoesNotExist:
            return 0, 0

        obj, was_created = DisclosureRecord.objects.get_or_create(
            company=company,
            pdf_filename=row["pdf_filename"],
            defaults={
                "disclosed_date": disclosed_date,
                "title":          row["title"],
                "pdf_url":        row["pdf_url"],
                "xbrl_url":       row["xbrl_url"],
            },
        )

        if was_created:
            return 1, 0

        # Existing record: only patch if something is missing
        patch = {}
        if not obj.xbrl_url and row["xbrl_url"]:
            patch["xbrl_url"] = row["xbrl_url"]
        if not obj.pdf_url:
            patch["pdf_url"] = row["pdf_url"]

        if patch:
            for field, value in patch.items():
                setattr(obj, field, value)
            obj.save(update_fields=list(patch.keys()))
            return 0, 1

        return 0, 0
