"""
Management command: fetch_edinet_codes

Downloads the EDINET code list ZIP from the FSA disclosure server and
populates Company.edinet_code for all matching TSE-listed companies.

No API key required — the code list is publicly available.

Usage:
  docker exec -it web python manage.py fetch_edinet_codes

CSV columns in EdinetcodeDlInfo.csv (cp932, first row is metadata):
  EDINETコード, 提出者種別, 上場区分, 連結の有無, 資本金, 決算日,
  提出者名, 提出者名（英字）, 提出者名（ヨミ）, 所在地, 提出者業種,
  証券コード, 提出者法人番号

証券コード is 5 digits: first 4 = stock code, last = exchange suffix.
"""

import io
import csv
import zipfile

import requests

from django.core.management.base import BaseCommand

from listings.models import Company

EDINET_CODE_LIST_URL = (
    "https://disclosure2dl.edinet-fsa.go.jp/searchdocument/codelist/Edinetcode.zip"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; research bot)",
}


class Command(BaseCommand):
    help = "Download the EDINET code list and populate Company.edinet_code."

    def handle(self, *args, **options):
        self.stdout.write("Downloading EDINET code list...")
        try:
            resp = requests.get(EDINET_CODE_LIST_URL, headers=HEADERS, timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            self.stderr.write(self.style.ERROR(f"Download failed: {e}"))
            return

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
            raw = zf.read(csv_name).decode("cp932")

        # First line is metadata (download date, count) — skip it.
        lines = raw.splitlines()
        reader = csv.DictReader(lines[1:])

        # Build mapping: 4-digit stock code → EDINET code
        edinet_map = {}
        for row in reader:
            code5 = row.get("証券コード", "").strip().strip('"')
            edinet = row.get("ＥＤＩＮＥＴコード", "").strip().strip('"')
            if not code5 or not edinet:
                continue
            stock_code = code5[:4]   # drop exchange suffix
            edinet_map[stock_code] = edinet

        self.stdout.write(f"  {len(edinet_map)} entries in code list.")

        # Update Company records
        updated = skipped = 0
        for company in Company.objects.all():
            edinet = edinet_map.get(company.stock_code)
            if not edinet:
                skipped += 1
                continue
            if company.edinet_code != edinet:
                company.edinet_code = edinet
                company.save(update_fields=["edinet_code"])
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(f"Done. updated={updated}  not_found={skipped}")
        )
