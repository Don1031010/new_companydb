import os

from django.core.management.base import BaseCommand

from financials.edinet_client import EdinetClient
from listings.models import Company


class Command(BaseCommand):
    help = "Fetch financial statements from EDINET for one or all companies"

    def add_arguments(self, parser):
        parser.add_argument("--code", type=str, help="Single stock code (e.g. 1301)")
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--all", action="store_true", help="Fetch for all companies")
        parser.add_argument(
            "--industry", type=str, metavar="CODE",
            help="Fetch for all companies in a 33-industry code (e.g. 3650 for 電気機器)",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("EDINET_API_KEY")
        if not api_key:
            self.stderr.write(self.style.WARNING("EDINET_API_KEY not set — requests may be rejected"))
        client = EdinetClient(api_key=api_key)
        year = options["year"]

        if options["all"]:
            companies = Company.objects.exclude(edinet_code="")
        elif options["code"]:
            companies = Company.objects.filter(stock_code=options["code"]).exclude(edinet_code="")
        elif options["industry"]:
            companies = Company.objects.filter(
                industry_33=options["industry"],
            ).exclude(edinet_code="")
        else:
            self.stderr.write("Provide --code, --industry, or --all")
            return

        verbose = options["verbosity"] >= 2

        for company in companies:
            self.stdout.write(self.style.MIGRATE_HEADING(f"Processing {company} ({company.edinet_code})..."))
            docs = client.get_docs_for_company(company.edinet_code, year=year)
            if not docs:
                self.stdout.write("  No filings found")
                continue
            for doc in docs:
                desc = doc.get("docDescription") or doc.get("formCode", "")
                period = doc.get("periodEnd") or ""
                self.stdout.write(self.style.WARNING(f"  → {desc}  period={period}  docID={doc['docID']}"))
                report, values = client.fetch_and_store(doc, verbose=verbose)
                if report:
                    fields = list(values.keys()) if values else []
                    self.stdout.write(f"     stored: {len(fields)} fields parsed")

        self.stdout.write(self.style.SUCCESS("Done."))
