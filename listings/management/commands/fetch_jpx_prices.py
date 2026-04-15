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
from django.utils import timezone

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


def _parse_price_time(value: str) -> datetime | None:
    """
    Parse trade time from the API (e.g. '15:30') and combine with today's date.
    The API field DPPT carries the time shown as (HH:MM) below the current price.
    Returns a timezone-aware datetime, or None if the value is missing/unparseable.
    """
    value = value.strip().lstrip("(").rstrip(")")
    if not value or value == "-":
        return None
    try:
        t = datetime.strptime(value, "%H:%M").time()
        today = timezone.localdate()
        return timezone.make_aware(datetime.combine(today, t))
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

    # Guard against null — API returns {"section1": {"data": null}} for delisted companies
    stock_data = data.get("section1", {}).get("data") or {}
    # Key is "<code>/T" for TSE; take first matching entry
    record = None
    for key, val in stock_data.items():
        if key.startswith(stock_code):
            record = val
            break

    if not record:
        logger.warning("No record in API response for %s", stock_code)
        return {}  # empty dict = no data (possibly delisted), not a network error

    share_price = _parse_price(record.get("DPP", "-"))
    yearly_high = _parse_price(record.get("YHPR", "-"))
    yearly_high_date = _parse_date(record.get("YHPD", "-"))
    yearly_low = _parse_price(record.get("YLPR", "-"))
    yearly_low_date = _parse_date(record.get("YLPD", "-"))
    # DPPT carries the trade time shown as (HH:MM) below the current price
    share_price_at = _parse_price_time(record.get("DPPT", "-"))

    if share_price is None and yearly_high is None and yearly_low is None:
        return {}  # empty dict signals "no data, skip cleanly"

    return {
        "share_price": share_price,
        "share_price_at": share_price_at,
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
            "--start-from", metavar="CODE",
            help="Resume from this stock code (inclusive), skipping everything before it",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Stop after N companies (0 = all)",
        )
        parser.add_argument(
            "--delay", type=float, default=0.5,
            help="Seconds between requests (default: 0.5)",
        )
        parser.add_argument(
            "--mark-delisted", action="store_true", default=False,
            help="Set status=watchlist on companies that return no price data (for review)",
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
        if options["start_from"]:
            qs = qs.filter(stock_code__gte=options["start_from"])
        if options["limit"]:
            qs = qs[: options["limit"]]

        total = qs.count()
        self.stdout.write(f"Fetching prices for {total} companies...\n")

        session = requests.Session()
        session.headers.update(SESSION_HEADERS)

        updated = errors = skipped = flagged = 0

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
                if options["mark_delisted"] and company.status == "active":
                    company.status = "watchlist"
                    company.save(update_fields=["status"])
                    self.stdout.write(self.style.WARNING("NO DATA — flagged as watchlist"))
                    flagged += 1
                else:
                    self.stdout.write(self.style.WARNING("NO DATA (possibly delisted)"))
                    skipped += 1
                continue

            company.share_price = data["share_price"]
            company.share_price_at = data["share_price_at"]
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

        summary = f"\nDone. updated={updated}  skipped={skipped}  errors={errors}"
        if flagged:
            summary += f"  flagged_watchlist={flagged}"
        self.stdout.write(self.style.MIGRATE_HEADING(summary))
