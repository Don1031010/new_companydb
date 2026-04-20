import os

from django.core.management.base import BaseCommand

from financials.edinet_client import EdinetClient
from listings.models import Company


class Command(BaseCommand):
    help = "Fetch financial statements from EDINET for one or all companies"

    def add_arguments(self, parser):
        parser.add_argument("--edinet-code", type=str, help="Single EDINET code")
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--all", action="store_true", help="Fetch for all companies")
        parser.add_argument(
            "--industry-33", type=str, metavar="CODE",
            help="Fetch for all companies in a 33-industry code (e.g. 3650 for 電気機器)",
        )
        parser.add_argument(
            "--industry-17", type=str, metavar="CODE",
            help="Fetch for all companies in a 17-industry code (e.g. 9 for 電機・精機)",
        )

    def handle(self, *args, **options):
        api_key = os.environ.get("EDINET_API_KEY")
        if not api_key:
            self.stderr.write(self.style.WARNING("EDINET_API_KEY not set — requests may be rejected"))
        client = EdinetClient(api_key=api_key)
        year = options["year"]

        if options["all"]:
            companies = Company.objects.exclude(edinet_code="")
        elif options["edinet_code"]:
            companies = Company.objects.filter(edinet_code=options["edinet_code"])
        elif options["industry_33"]:
            companies = Company.objects.filter(
                industry_33=options["industry_33"],
            ).exclude(edinet_code="")
        elif options["industry_17"]:
            companies = Company.objects.filter(
                industry_17=options["industry_17"],
            ).exclude(edinet_code="")
        else:
            self.stderr.write("Provide --edinet-code, --industry-33, --industry-17, or --all")
            return

        verbose = options["verbosity"] >= 2

        for company in companies:
            self.stdout.write(f"Processing {company} ({company.edinet_code})...")
            docs = client.get_docs_for_company(company.edinet_code, year=year)
            if not docs:
                self.stdout.write(f"  No filings found")
                continue
            for doc in docs:
                desc = doc.get("docDescription") or doc.get("formCode", "")
                period = doc.get("periodEnd") or ""
                self.stdout.write(f"  → {desc}  period={period}  docID={doc['docID']}")
                report, values = client.fetch_and_store(doc, verbose=verbose)
                if report:
                    fields = list(values.keys()) if values else []
                    self.stdout.write(f"     stored: {len(fields)} fields parsed")

        self.stdout.write(self.style.SUCCESS("Done."))
