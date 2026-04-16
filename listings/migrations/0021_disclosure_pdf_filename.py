"""
Add pdf_filename to DisclosureRecord and replace the (company, pdf_url)
unique_together with a conditional unique constraint on (company, pdf_filename).

pdf_filename is the basename of the PDF (e.g. 140120260406599058.pdf).
It is stable across TDnet and JPX because both sites serve the same file
under the same name.  pdf_url therefore no longer needs to be unique —
TDnet URLs are temporary (~1 month); JPX runs overwrite them with permanent
URLs using pdf_filename as the lookup key.
"""

import os
from django.db import migrations, models


def populate_pdf_filename(apps, schema_editor):
    DisclosureRecord = apps.get_model("listings", "DisclosureRecord")
    batch = []
    for record in DisclosureRecord.objects.exclude(pdf_url=""):
        record.pdf_filename = os.path.basename(record.pdf_url)
        batch.append(record)
        if len(batch) >= 500:
            DisclosureRecord.objects.bulk_update(batch, ["pdf_filename"])
            batch.clear()
    if batch:
        DisclosureRecord.objects.bulk_update(batch, ["pdf_filename"])


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0020_alter_disclosurerecord_options_and_more"),
    ]

    operations = [
        # 1. Add the new field (nullable/blank so existing rows don't need a default)
        migrations.AddField(
            model_name="disclosurerecord",
            name="pdf_filename",
            field=models.CharField(
                blank=True,
                max_length=100,
                verbose_name="PDFファイル名",
                help_text="e.g. 140120260406599058.pdf — stable across TDnet and JPX",
            ),
        ),
        # 2. Backfill from existing pdf_url values
        migrations.RunPython(populate_pdf_filename, migrations.RunPython.noop),
        # 3. Drop the old (company, pdf_url) unique_together
        migrations.AlterUniqueTogether(
            name="disclosurerecord",
            unique_together=set(),
        ),
        # 4. Add conditional unique constraint on (company, pdf_filename)
        migrations.AddConstraint(
            model_name="disclosurerecord",
            constraint=models.UniqueConstraint(
                fields=["company", "pdf_filename"],
                condition=models.Q(pdf_filename__gt=""),
                name="unique_disclosure_company_filename",
            ),
        ),
    ]
