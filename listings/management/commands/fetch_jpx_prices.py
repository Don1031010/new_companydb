"""
Management command: fetch_jpx_prices

Fetches current share price data from the JPX JSON API for each TSE-listed
company and updates the following fields:
  - share_price      (現在値 — DPP)
  - yearly_high      (年初来高値 — YHPR)
  - yearly_high_date (年初来高値の日付 — YHPD)
  - yearly_low       (年初来安値 — YLPR)
  - yearly_low_date  (年初来安値の日付 — YLPD)
  - market_cap       (recomputed automatically via Company.save())

Runs via the web container (no Playwright required):
  docker exec -it web python manage.py fetch_jpx_prices
  docker exec -it web python manage.py fetch_jpx_prices --codes 6758 7203
  docker exec -it web python manage.py fetch_jpx_prices --limit 10

API endpoint confirmed from stock_detail.js:
  GET https://quote.jpx.co.jp/jpxhp/jcgi/wrap/qjsonp.aspx?F=ctl/stock_detail&qcode=<code>
  Response: { "section1": { "data": { "<code>/T": { DPP, YHPR, YHPD, YLPR, YLPD, ... } } } }
"""

import time
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from django.core.management.base import BaseCommand

from listings.models import Company

logger = logging.getLogger(__name__)

API_URL = "https://quote.jpx.co.jp/jpxhp/jcgi/wrap/qjsonp.aspx"

SESSION_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://quote.jpx.co.jp/jpxhp/main/index.aspx",
    "Accept": "application/json, text/javascript, */*",
    "Accept-Language": "ja-JP,ja;q=0.9",
}


def _parse_price(value: str) -> Decimal | None:
    """Parse '3,333' → Decimal. Returns None for '-' or empty."""
    value = value.strip().replace(",", "")
    if not value or value == "-":
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _parse_date(value: str) -> date | None:
    """Parse 'YYYY/MM/DD' → date. Returns None for '-' or empty."""
    value = value.strip()
    if not value or value == "-":
        return None
    try:
        return datetime.strptime(value, "%Y/%m/%d").date()
    except ValueError:
        return None


def _fetch_prices(session: requests.Session, stock_code: str) -> dict | None:
    """
    Fetch price data for one stock code via the JPX JSON API.
    Returns a dict with share_price, yearly_high, yearly_high_date,
    yearly_low, yearly_low_date — or None on failure.
    """
    try:
        resp = session.get(
            API_URL,
            params={"F": "ctl/stock_detail", "qcode": stock_code},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("Failed to fetch %s: %s", stock_code, e)
        return None

    stock_data = data.get("section1", {}).get("data", {})
    # Key is "<code>/T" for TSE; take first matching entry
    record = None
    for key, val in stock_data.items():
        if key.startswith(stock_code):
            record = val
            break

    if not record:
        logger.warning("No record in API response for %s", stock_code)
        return None

    share_price = _parse_price(record.get("DPP", "-"))
    yearly_high = _parse_price(record.get("YHPR", "-"))
    yearly_high_date = _parse_date(record.get("YHPD", "-"))
    yearly_low = _parse_price(record.get("YLPR", "-"))
    yearly_low_date = _parse_date(record.get("YLPD", "-"))

    if share_price is None and yearly_high is None and yearly_low is None:
        return {}  # empty dict signals "no data, skip cleanly"

    return {
        "share_price": share_price,
        "yearly_high": yearly_high,
        "yearly_high_date": yearly_high_date,
        "yearly_low": yearly_low,
        "yearly_low_date": yearly_low_date,
    }


class Command(BaseCommand):
    help = "Fetch current share prices from the JPX API and update Company records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codes", nargs="+", metavar="CODE",
            help="Only fetch prices for these stock codes (e.g. 6758 7203)",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Stop after N companies (0 = all)",
        )
        parser.add_argument(
            "--delay", type=float, default=0.5,
            help="Seconds between requests (default: 0.5)",
        )

    def handle(self, *args, **options):
        qs = (
            Company.objects
            .filter(is_non_jpx=False)
            .exclude(listings__market_segment="tse_pro")
            .order_by("stock_code")
        )
        if options["codes"]:
            qs = qs.filter(stock_code__in=options["codes"])
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        self.stdout.write(f"Fetching prices for {total} companies...\n")

        session = requests.Session()
        session.headers.update(SESSION_HEADERS)

        updated = errors = skipped = 0

        for i, company in enumerate(qs, start=1):
            if i > 1:
                time.sleep(options["delay"])

            self.stdout.write(
                f"  [{i}/{total}] {company.stock_code} {company.name_ja} ... ",
                ending="",
            )
            self.stdout.flush()

            data = _fetch_prices(session, company.stock_code)
            if data is None:
                self.stdout.write(self.style.ERROR("FAILED"))
                errors += 1
                continue
            if not data:
                self.stdout.write(self.style.WARNING("NO DATA"))
                skipped += 1
                continue

            company.share_price = data["share_price"]
            company.yearly_high = data["yearly_high"]
            company.yearly_high_date = data["yearly_high_date"]
            company.yearly_low = data["yearly_low"]
            company.yearly_low_date = data["yearly_low_date"]
            # market_cap is recomputed in Company.save()
            company.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"OK  株価={data['share_price']}  "
                    f"高={data['yearly_high']}({data['yearly_high_date']})  "
                    f"安={data['yearly_low']}({data['yearly_low_date']})"
                )
            )
            updated += 1

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nDone. updated={updated}  skipped={skipped}  errors={errors}"
            )
        )
