import re

from django.core.management.base import BaseCommand

from financials.tse_client import TseClient, detect_report_type
from listings.models import Company, DisclosureRecord

# Titles that identify 決算短信 (earnings releases) as opposed to other disclosures
KESSAN_PATTERN = re.compile(r'決算短信|中間決算短信')


class Command(BaseCommand):
    help = "Fetch quarterly/annual financials from TDnet XBRL (決算短信)"

    def add_arguments(self, parser):
        parser.add_argument("--edinet-code", type=str, help="Single EDINET code (e.g. E00012)")
        parser.add_argument("--stock-code", type=str, help="Single stock code (e.g. 1301)")
        parser.add_argument(
            "--industry-33", type=str, metavar="CODE",
            help="All companies in a 33-industry code",
        )
        parser.add_argument(
            "--industry-17", type=str, metavar="CODE",
            help="All companies in a 17-industry code",
        )
        parser.add_argument("--all", action="store_true", help="All companies")
        parser.add_argument(
            "--year", type=int,
            help="Limit to disclosures in this fiscal year (e.g. 2025 matches '2025年')",
        )

    def handle(self, *args, **options):
        client = TseClient()
        verbose = options["verbosity"] >= 2
        year_filter = options.get("year")

        if options["all"]:
            companies = Company.objects.exclude(edinet_code="")
        elif options["edinet_code"]:
            companies = Company.objects.filter(edinet_code=options["edinet_code"])
        elif options["stock_code"]:
            companies = Company.objects.filter(stock_code=options["stock_code"])
        elif options["industry_33"]:
            companies = Company.objects.filter(industry_33=options["industry_33"]).exclude(edinet_code="")
        elif options["industry_17"]:
            companies = Company.objects.filter(industry_17=options["industry_17"]).exclude(edinet_code="")
        else:
            self.stderr.write("Provide --edinet-code, --industry-33, --industry-17, or --all")
            return

        for company in companies:
            self.stdout.write(f"Processing {company} ({company.edinet_code})...")

            disclosures = DisclosureRecord.objects.filter(
                company=company,
                xbrl_url__gt="",
            ).filter(title__regex=r'決算短信|中間決算短信').order_by("-disclosed_date")

            if year_filter:
                year_str = str(year_filter)
                disclosures = disclosures.filter(title__contains=f"{year_str}年")

            if not disclosures.exists():
                if verbose:
                    self.stdout.write("  No 決算短信 XBRL found")
                continue

            for disc in disclosures:
                if verbose:
                    self.stdout.write(f"  {disc.disclosed_date}  {disc.title}")
                report, values = client.fetch_and_store(disc, verbose=verbose)
                if verbose and report:
                    status = "created" if values is not None else "no data"
                    fields = list(values.keys()) if values else []
                    self.stdout.write(f"  → pk={report.pk} FY{report.fiscal_year}Q{report.fiscal_quarter}  fields={fields}")

        self.stdout.write(self.style.SUCCESS("Done."))
