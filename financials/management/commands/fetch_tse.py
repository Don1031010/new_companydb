import re

from django.core.management.base import BaseCommand

from financials.tse_client import TseClient
from listings.models import Company, DisclosureRecord


class Command(BaseCommand):
    help = "Fetch quarterly/annual financials from TDnet XBRL (決算短信)"

    def add_arguments(self, parser):
        parser.add_argument("--code", type=str, help="Single stock code (e.g. 1301)")
        parser.add_argument(
            "--industry", type=str, metavar="CODE",
            help="All companies in a 33-industry code",
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
        elif options["code"]:
            companies = Company.objects.filter(stock_code=options["code"])
        elif options["industry"]:
            companies = Company.objects.filter(industry_33=options["industry"]).exclude(edinet_code="")
        else:
            self.stderr.write("Provide --code, --industry, or --all")
            return

        for company in companies:
            self.stdout.write(self.style.MIGRATE_HEADING(f"Processing {company} ({company.edinet_code})..."))

            disclosures = DisclosureRecord.objects.filter(
                company=company,
                xbrl_url__gt="",
            ).filter(title__regex=r'決算短信|中間決算短信').order_by("disclosed_date")

            if year_filter:
                disclosures = disclosures.filter(title__contains=f"{year_filter}年")

            if not disclosures.exists():
                self.stdout.write("  No 決算短信 XBRL found")
                continue

            for disc in disclosures:
                self.stdout.write(self.style.WARNING(f"  → {disc.disclosed_date}  {disc.title}"))
                report, values = client.fetch_and_store(disc, verbose=verbose)
                if verbose and report:
                    fields = list(values.keys()) if values else []
                    self.stdout.write(f"     pk={report.pk} FY{report.fiscal_year}Q{report.fiscal_quarter}  fields={fields}")

        self.stdout.write(self.style.SUCCESS("Done."))
