"""
Populate the Holiday table from the `holidays` library.

Usage:
    python manage.py populate_holidays                    # current + next year
    python manage.py populate_holidays --years 2024 2025 2026
    python manage.py populate_holidays --years 2024 --countries JP CN
    python manage.py populate_holidays --clear            # delete all first
"""

from datetime import date

from django.core.management.base import BaseCommand

import holidays as holidays_lib

from cal.models import Holiday

SUPPORTED = {
    "JP": ("JP", "日本"),
    "CN": ("CN", "中国"),
    "US": ("US", "米国"),
}


class Command(BaseCommand):
    help = "Populate Holiday table from the holidays library (JP, CN, US)"

    def add_arguments(self, parser):
        today = date.today()
        parser.add_argument(
            "--years", nargs="+", type=int,
            default=[today.year, today.year + 1],
            metavar="YEAR",
            help="Years to populate (default: current + next year)",
        )
        parser.add_argument(
            "--countries", nargs="+",
            default=list(SUPPORTED.keys()),
            choices=list(SUPPORTED.keys()),
            metavar="COUNTRY",
            help="Country codes to populate (default: JP CN US)",
        )
        parser.add_argument(
            "--clear", action="store_true",
            help="Delete existing holiday entries before populating",
        )

    def handle(self, *args, **options):
        years = options["years"]
        countries = options["countries"]

        if options["clear"]:
            deleted, _ = Holiday.objects.filter(country__in=countries).delete()
            self.stdout.write(f"  Cleared {deleted} existing entries.\n")

        total_created = total_skipped = 0

        for country in countries:
            for year in years:
                try:
                    hl = holidays_lib.country_holidays(country, years=year)
                except NotImplementedError:
                    self.stdout.write(self.style.WARNING(
                        f"  {country} {year}: not supported by holidays library, skipping."
                    ))
                    continue

                created = skipped = 0
                for h_date, h_name in sorted(hl.items()):
                    _, was_created = Holiday.objects.update_or_create(
                        date=h_date,
                        country=country,
                        defaults={"name": h_name},
                    )
                    if was_created:
                        created += 1
                    else:
                        skipped += 1

                self.stdout.write(
                    f"  {country} {year}: {created} created, {skipped} updated"
                )
                total_created += created
                total_skipped += skipped

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {total_created} created, {total_skipped} updated."
        ))
