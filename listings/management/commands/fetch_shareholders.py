"""
Management command: fetch_shareholders

Fetches major shareholder (大株主) data from EDINET annual securities reports
(有価証券報告書) and updates ShareRecord for each company.

Requires an EDINET API key in the environment:
  EDINET_API_KEY=your_key_here

Usage:
  docker exec -it web python manage.py fetch_shareholders
  docker exec -it web python manage.py fetch_shareholders --codes 6758 7203
  docker exec -it web python manage.py fetch_shareholders --industry 3650
  docker exec -it web python manage.py fetch_shareholders --industry 3600 3650 3700
  docker exec -it web python manage.py fetch_shareholders --days 400

Two-phase operation:
  Phase 1 — scan the document list API for the last N days to build an index
             of {edinet_code: (docID, period_end)} for 有価証券報告書.
  Phase 2 — for each company, download the XBRL-to-CSV ZIP (type=5),
             parse shareholders from the structured CSV, and update ShareRecord.

CSV structure (UTF-16, tab-separated):
  col 0: XBRL element (e.g. jpcrp_cor:NameMajorShareholders)
  col 2: context     (e.g. CurrentYearInstant_No1MajorShareholdersMember)
  col 8: value

API reference:
  GET https://api.edinet-fsa.go.jp/api/v2/documents.json
      ?date=YYYY-MM-DD&type=2&Subscription-Key=KEY
  GET https://api.edinet-fsa.go.jp/api/v2/documents/{docID}
      ?type=5&Subscription-Key=KEY  → XBRL-to-CSV ZIP
"""

import csv
import io
import os
import re
import time
import zipfile
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

from django.core.management.base import BaseCommand, CommandError

from django.db import models
from django.db.models import Q
from listings.models import (
    Company, Shareholder, ShareRecord, MajorShareholder,
    CompanyShareInfo, EDINETDocument, SOURCE_CHOICES,
)

logger = logging.getLogger(__name__)

EDINET_API = "https://api.edinet-fsa.go.jp/api/v2"
ORDINANCE_CODE = "010"      # Financial Instruments and Exchange Act
# 030000/030001 = 有価証券報告書 (annual)            → CSV prefix: jpcrp030000
# 040000/040001 = 半期報告書 (old format, pre-2024)  → CSV prefix: jpcrp040000
# 043A00        = 半期報告書 (new format, post-2024) → CSV prefix: jpcrp043A00
FORM_CODE_PREFIXES = ("0300", "0400", "043A")

# XBRL element names for major shareholders
ELEM_NAME = "jpcrp_cor:NameMajorShareholders"
ELEM_ADDR = "jpcrp_cor:AddressMajorShareholders"
ELEM_SHARES = "jpcrp_cor:NumberOfSharesHeld"
ELEM_RATIO = "jpcrp_cor:ShareholdingRatio"
ELEM_TREASURY = "jpcrp_cor:TotalNumberOfSharesHeldTreasurySharesEtc"
ELEM_TOTAL_SHARES = "jpcrp_cor:NumberOfIssuedSharesAsOfFiscalYearEndIssuedSharesTotalNumberOfSharesEtc"
ELEM_PERIOD_END = "jpdei_cor:CurrentPeriodEndDateDEI"

# Match context like CurrentYearInstant_No3MajorShareholdersMember
RE_RANK = re.compile(r"No(\d+)MajorShareholdersMember")


def _sync_edinet_docs(session: requests.Session, api_key: str, days: int, stdout) -> int:
    """
    Fetch document list entries from EDINET and store them in EDINETDocument.
    Only scans dates newer than the latest record already in the DB (or `days`
    days back if the table is empty). Returns the count of new rows inserted.
    """
    today = date.today()
    latest = EDINETDocument.objects.aggregate(d=models.Max("submit_date"))["d"]

    if latest:
        # Re-scan from one day before the latest stored date to catch any
        # documents that may have been added after our last run.
        scan_from = latest - timedelta(days=1)
        total_days = (today - scan_from).days + 1
        stdout.write(f"  DB has entries up to {latest}. Scanning {total_days} new day(s).\n")
    else:
        scan_from = today - timedelta(days=days)
        total_days = days
        stdout.write(f"  DB empty. Scanning {total_days} days back to {scan_from}.\n")

    existing_ids = set(
        EDINETDocument.objects.filter(
            submit_date__gte=scan_from
        ).values_list("doc_id", flat=True)
    )

    new_docs = []
    for i in range(total_days):
        target = scan_from + timedelta(days=i)
        try:
            resp = session.get(
                f"{EDINET_API}/documents.json",
                params={"date": target.isoformat(), "type": 2, "Subscription-Key": api_key},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            logger.warning("documents.json failed for %s: %s", target, e)
            time.sleep(1)
            continue

        for doc in data.get("results", []):
            doc_id = doc.get("docID")
            edinet_code = doc.get("edinetCode") or ""
            if not doc_id or doc_id in existing_ids or not edinet_code:
                continue

            period_end = None
            raw_end = doc.get("periodEnd")
            if raw_end:
                try:
                    period_end = datetime.strptime(raw_end, "%Y-%m-%d").date()
                except ValueError:
                    pass

            new_docs.append(EDINETDocument(
                doc_id=doc_id,
                edinet_code=edinet_code,
                ordinance_code=doc.get("ordinanceCode") or "",
                form_code=doc.get("formCode") or "",
                period_end=period_end,
                submit_date=target,
                description=(doc.get("docDescription") or "")[:300],
                withdrawn=doc.get("withdrawalStatus") != "0",
            ))
            existing_ids.add(doc_id)

        time.sleep(0.3)

    if new_docs:
        EDINETDocument.objects.bulk_create(new_docs, ignore_conflicts=True)

    stdout.write(f"  Synced {len(new_docs)} new document entries.\n")
    return len(new_docs)


def _build_index_from_db() -> dict:
    """
    Build { edinet_code: {"docID": ..., "period_end": date} } from the
    EDINETDocument table.

    Picks the report with the most recent period_end date across all form types
    (annual 0300xx, semi-annual 0400xx / 043Axx).  A September semi-annual report
    will therefore be preferred over the prior March annual report.
    """
    qs = (
        EDINETDocument.objects
        .filter(
            ordinance_code=ORDINANCE_CODE,
            withdrawn=False,
        )
        .filter(
            Q(form_code__startswith="0300") |
            Q(form_code__startswith="0400") |
            Q(form_code__startswith="043A")
        )
        .order_by("edinet_code", "-submit_date")
    )

    best: dict = {}  # edinet_code -> best doc entry so far

    for doc in qs:
        if not doc.edinet_code:
            continue
        entry = {"docID": doc.doc_id, "period_end": doc.period_end}
        existing = best.get(doc.edinet_code)
        if not existing:
            best[doc.edinet_code] = entry
            continue

        # Prefer the report with the later period_end.
        # If period_end is equal or missing, prefer annual over semi-annual.
        new_end = doc.period_end
        cur_end = existing["period_end"]
        if new_end and cur_end:
            if new_end > cur_end:
                best[doc.edinet_code] = entry
        elif new_end and not cur_end:
            best[doc.edinet_code] = entry
        # If same period_end, keep whichever was already stored (most recent submit_date
        # wins due to ORDER BY -submit_date above, so first seen = most recently filed)

    return best


def _parse_csv(csv_bytes: bytes) -> tuple[list[dict] | None, int | None, int | None, date | None]:
    """
    Parse the XBRL-to-CSV file from the EDINET type=5 ZIP.

    Returns a tuple of:
      - shareholders: list of {name, address, shares, percentage} sorted by rank,
                      or None if not found.
      - total_shares: total issued shares from the filing, or None.
      - treasury_shares: total treasury share count (自己株式数), or None.
      - period_end: the actual period end date from the filing (CurrentPeriodEndDateDEI),
                    or None. Use this in preference to the API's periodEnd field, which
                    may reflect the fiscal year end rather than the interim period end.

    ShareholdingRatio in the CSV is a decimal (0.1881 = 18.81%) — stored as %.
    """
    raw = csv_bytes.decode("utf-16", errors="replace")
    reader = csv.reader(io.StringIO(raw), delimiter="\t")

    by_rank: dict[int, dict] = {}
    total_shares: int | None = None
    treasury_shares: int | None = None
    _treasury_from_row1 = False
    period_end: date | None = None

    for row in reader:
        if len(row) < 9:
            continue
        element = row[0].strip().strip('"')
        context = row[2].strip().strip('"')
        value = row[8].strip().strip('"')

        # Period end date from the filing itself (more reliable than API periodEnd)
        if element == ELEM_PERIOD_END:
            try:
                period_end = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                pass
            continue

        # Total shares issued — use the aggregate FilingDateInstant row (no member suffix)
        if element == ELEM_TOTAL_SHARES and context == "FilingDateInstant" and total_shares is None:
            try:
                total_shares = int(value.replace(",", ""))
            except ValueError:
                pass
            continue

        # Treasury shares: Row1Member = pure 自己株式; plain context = total incl. cross-holdings.
        # Prefer Row1Member when present; fall back to plain aggregate only if Row1Member absent.
        if element == ELEM_TREASURY:
            _base_ctxs = ("CurrentYearInstant", "InterimInstant", "CurrentQuarterInstant")
            _is_row1 = any(context == f"{b}_Row1Member" for b in _base_ctxs)
            _is_total = context in _base_ctxs
            if _is_row1:
                try:
                    treasury_shares = int(value.replace(",", ""))
                    _treasury_from_row1 = True
                except ValueError:
                    pass
            elif _is_total and not _treasury_from_row1:
                try:
                    treasury_shares = int(value.replace(",", ""))
                except ValueError:
                    pass
            continue

        if "MajorShareholdersMember" not in context:
            continue
        # Accept annual (CurrentYearInstant), semi-annual (InterimInstant),
        # and quarterly (CurrentQuarterInstant) contexts
        if not context.startswith(("CurrentYearInstant", "InterimInstant", "CurrentQuarterInstant")):
            continue

        m = RE_RANK.search(context)
        if not m:
            continue
        rank = int(m.group(1))
        sh = by_rank.setdefault(rank, {})

        if element == ELEM_NAME:
            sh["name"] = value
        elif element == ELEM_ADDR:
            sh["address"] = value
        elif element == ELEM_SHARES:
            try:
                sh["shares"] = int(value.replace(",", ""))
            except ValueError:
                pass
        elif element == ELEM_RATIO:
            try:
                sh["percentage"] = (Decimal(value) * 100).quantize(Decimal("0.01"))
            except InvalidOperation:
                pass

    result = []
    for rank in sorted(by_rank.keys()):
        sh = by_rank[rank]
        if not sh.get("name") or sh.get("percentage") is None:
            continue
        result.append({
            "name": sh["name"],
            "address": sh.get("address", ""),
            "shares": sh.get("shares"),
            "percentage": sh["percentage"],
        })

    return (result or None), total_shares, treasury_shares, period_end


def _fetch_and_parse(
    session: requests.Session, api_key: str, doc_id: str
) -> tuple[list[dict] | None, int | None, int | None, date | None, str | None]:
    """
    Download the XBRL-to-CSV ZIP for doc_id and parse major shareholders,
    total shares, treasury shares, and period end date.

    Returns (shareholders, total_shares, treasury_shares, period_end, reason).
    On success: reason is None.
    On failure: shareholders is None and reason describes what went wrong.
    """
    try:
        resp = session.get(
            f"{EDINET_API}/documents/{doc_id}",
            params={"type": 5, "Subscription-Key": api_key},
            timeout=120,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        return None, None, None, None, f"download error: {e}"

    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            all_names = zf.namelist()
            csv_files = [
                n for n in all_names
                if any(p in n for p in ("jpcrp030000", "jpcrp040000", "jpcrp040300", "jpcrp043A00"))
                and n.endswith(".csv")
            ]
            if not csv_files:
                csv_in_zip = [n for n in all_names if n.endswith(".csv")]
                detail = ", ".join(csv_in_zip[:6]) if csv_in_zip else "no .csv files in ZIP"
                return None, None, None, None, f"no matching CSV — ZIP contains: {detail}"
            shareholders, total_shares, treasury_shares, period_end = _parse_csv(zf.read(csv_files[0]))
            if not shareholders:
                return None, total_shares, treasury_shares, period_end, "CSV parsed but no shareholder rows found"
            return shareholders, total_shares, treasury_shares, period_end, None
    except zipfile.BadZipFile:
        return None, None, None, None, "bad ZIP file"


class Command(BaseCommand):
    help = "Fetch major shareholder data from EDINET and update ShareRecord."

    def add_arguments(self, parser):
        parser.add_argument(
            "--codes", nargs="+", metavar="CODE",
            help="Only fetch shareholders for these stock codes",
        )
        parser.add_argument(
            "--from-code", metavar="CODE",
            help="Start from this stock code and continue to the end (inclusive)",
        )
        parser.add_argument(
            "--industry", nargs="+", metavar="INDUSTRY_33",
            help="Only fetch shareholders for companies in these 33-industry codes (e.g. 3650 3600)",
        )
        parser.add_argument(
            "--days", type=int, default=400,
            help="How many past days to scan for annual reports (default: 400)",
        )
        parser.add_argument(
            "--delay", type=float, default=1.0,
            help="Seconds between document downloads (default: 1.0)",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("EDINET_API_KEY", "").strip()
        if not api_key:
            raise CommandError(
                "EDINET_API_KEY is not set. "
                "Register at https://api.edinet-fsa.go.jp/ and add it to .env."
            )

        qs = Company.objects.filter(is_non_jpx=False).exclude(edinet_code="")
        if options["codes"]:
            qs = qs.filter(stock_code__in=options["codes"])
        if options["from_code"]:
            qs = qs.filter(stock_code__gte=options["from_code"])
        if options["industry"]:
            qs = qs.filter(industry_33__in=options["industry"])

        companies = list(qs.order_by("stock_code"))
        self.stdout.write(f"{len(companies)} companies to process.\n")

        session = requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        })

        # ── Phase 1: sync document index ─────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("=== Phase 1: Syncing document index ==="))
        _sync_edinet_docs(session, api_key, options["days"], self.stdout)
        doc_index = _build_index_from_db()

        # ── Phase 2: fetch & parse shareholders ───────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING("\n=== Phase 2: Fetching shareholders ===\n"))

        updated = skipped = errors = 0
        total = len(companies)

        for i, company in enumerate(companies, start=1):
            entry = doc_index.get(company.edinet_code)
            if not entry:
                self.stdout.write(
                    f"  [{i}/{total}] {company.stock_code} {company.name_ja} — "
                    + self.style.WARNING("no report found, skipping")
                )
                skipped += 1
                continue

            self.stdout.write(
                f"  [{i}/{total}] {company.stock_code} {company.name_ja} "
                f"(docID={entry['docID']}) ... ",
                ending="",
            )
            self.stdout.flush()

            if i > 1:
                time.sleep(options["delay"])

            shareholders, total_shares, treasury_shares, csv_period_end, reason = _fetch_and_parse(session, api_key, entry["docID"])
            if not shareholders:
                self.stdout.write(self.style.ERROR(f"NO DATA — {reason}"))
                errors += 1
                continue

            as_of_date = csv_period_end or entry["period_end"]
            doc_id = entry["docID"]
            edinet_doc = EDINETDocument.objects.filter(doc_id=doc_id).first()

            # Determine source from form_code
            form_code = edinet_doc.form_code if edinet_doc else ""
            if form_code.startswith("0300"):
                source = "edinet_annual"
            else:
                source = "edinet_interim"

            # Upsert ShareRecord snapshot
            snapshot, _ = ShareRecord.objects.update_or_create(
                company=company,
                as_of_date=as_of_date,
                defaults={
                    "edinet_doc": edinet_doc,
                    "total_shares": total_shares,
                    "treasury_shares": treasury_shares,
                },
            )

            # Replace MajorShareholder entries for this snapshot
            snapshot.entries.all().delete()
            for rank, sh in enumerate(shareholders, start=1):
                shareholder, _ = Shareholder.objects.get_or_create(
                    name=sh["name"],
                    defaults={"address": sh["address"]},
                )
                MajorShareholder.objects.create(
                    share_record=snapshot,
                    shareholder=shareholder,
                    rank=rank,
                    shares=sh["shares"],
                    percentage=sh["percentage"],
                )

            # Upsert CompanyShareInfo for signal to sync shares_outstanding
            if total_shares is not None or treasury_shares is not None:
                CompanyShareInfo.objects.update_or_create(
                    company=company,
                    as_of_date=as_of_date,
                    defaults={
                        "source": source,
                        "total_shares": total_shares,
                        "treasury_shares": treasury_shares,
                    },
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"OK ({len(shareholders)} shareholders"
                    + (f", 発行済={total_shares:,}" if total_shares else "")
                    + (f", 自己株={treasury_shares:,}" if treasury_shares else "")
                    + ")"
                )
            )
            updated += 1

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nDone. updated={updated}  skipped={skipped}  errors={errors}"
            )
        )
