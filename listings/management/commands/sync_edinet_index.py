"""
sync_edinet_index
=================
Bulk-populates the EDINETDocument table by scanning the EDINET document list
API day by day.  Run this once (or periodically) so that fetch_edinet and
fetch_shareholders can use the cache instead of doing per-company day-by-day
scans.

Only documents whose EDINET code matches a Company in the database are stored.
Already-synced dates are skipped automatically, so re-running is safe and fast.

Usage:
    python manage.py sync_edinet_index              # past 5 years
    python manage.py sync_edinet_index --years 3
    python manage.py sync_edinet_index --days 400   # fine-grained
"""

import os
import time
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from financials.edinet_client import EdinetClient
from listings.models import Company, EDINETDocument, SyncedDate

# Form codes worth caching (financial reports + shareholder reports)
FORM_CODES = {
    "030000",  # 有価証券報告書 (annual)
    "040000",  # 半期報告書 (old semi-annual, for shareholders)
    "040001",  # 半期報告書 amendment
    "043000",  # 四半期報告書 Q2 (pre-2024)
    "043001",  # 四半期報告書 Q1/Q3 (pre-2024)
    "043A00",  # 半期報告書 (post-2024 reform)
}


class Command(BaseCommand):
    help = "Bulk-sync EDINET document index into EDINETDocument table (one-time cache warm-up)"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--years", type=int, default=5, help="Number of past years to scan (default: 5)")
        group.add_argument("--days", type=int, help="Number of past days to scan")
        parser.add_argument("--delay", type=float, default=0.5, help="Seconds between API requests (default: 0.5)")
        parser.add_argument("--force", action="store_true", help="Re-scan dates already in the DB")

    def handle(self, *args, **options):
        api_key = os.environ.get("EDINET_API_KEY")
        if not api_key:
            self.stderr.write(self.style.WARNING("EDINET_API_KEY not set — requests may fail"))

        client = EdinetClient(api_key=api_key, throttle=options["delay"])

        # Date range
        today = date.today()
        if options["days"]:
            start = today - timedelta(days=options["days"])
        else:
            start = today.replace(year=today.year - options["years"])
        end = today

        # Build set of edinet_codes for companies in our DB
        known_codes = set(
            Company.objects.exclude(edinet_code="").values_list("edinet_code", flat=True)
        )
        self.stdout.write(f"Known companies: {len(known_codes)}")

        # Build set of dates already synced (skip unless --force)
        if not options["force"]:
            synced_dates = set(
                SyncedDate.objects.filter(date__gte=start)
                .values_list("date", flat=True)
            )
            self.stdout.write(f"Already-synced dates in range: {len(synced_dates)}")
        else:
            synced_dates = set()

        # Collect weekdays to scan
        scan_dates = [
            start + timedelta(days=i)
            for i in range((end - start).days + 1)
            if (start + timedelta(days=i)).weekday() < 5  # Mon–Fri
            and (start + timedelta(days=i)) not in synced_dates
        ]

        total = len(scan_dates)
        if total == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to scan — all dates already synced."))
            return

        self.stdout.write(f"Scanning {total} dates from {start} to {end} …")

        stored = 0
        skipped = 0

        for i, current in enumerate(scan_dates, 1):
            try:
                docs = client.get_docs_for_date(current, doc_type=2)
            except Exception as e:
                self.stderr.write(f"  {current}: API error — {e}")
                continue

            for doc in docs:
                code = doc.get("edinetCode", "")
                form = doc.get("formCode", "")
                if code not in known_codes or form not in FORM_CODES:
                    continue

                doc_id = doc.get("docID", "")
                if not doc_id:
                    continue

                period_raw = doc.get("periodEnd") or doc.get("periodOfReport")
                try:
                    from datetime import datetime
                    period_end = datetime.strptime(period_raw, "%Y-%m-%d").date() if period_raw else None
                except (ValueError, TypeError):
                    period_end = None

                withdrawn = doc.get("docInfoEditStatus") in ("1", 1)

                _, created = EDINETDocument.objects.update_or_create(
                    doc_id=doc_id,
                    defaults=dict(
                        edinet_code=code,
                        ordinance_code=doc.get("ordinanceCode", ""),
                        form_code=form,
                        period_end=period_end,
                        submit_date=current,
                        description=doc.get("docDescription", "")[:300],
                        withdrawn=withdrawn,
                    ),
                )
                if created:
                    stored += 1
                else:
                    skipped += 1

            SyncedDate.objects.get_or_create(date=current)

            if i % 10 == 0 or i == total:
                self.stdout.write(
                    f"  {i}/{total} dates scanned  "
                    f"({stored} new, {skipped} updated)  last: {current}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. {stored} new documents stored, {skipped} updated, "
                f"{total} dates scanned."
            )
        )
