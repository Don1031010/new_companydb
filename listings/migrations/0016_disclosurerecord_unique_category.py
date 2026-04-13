from django.db import migrations


class Migration(migrations.Migration):
    """
    Change DisclosureRecord unique_together from (company, pdf_url) to
    (company, category, pdf_url) so that the same document can appear as
    both a 決算情報 (1101) row and a 決定事実・発生事実 (1102) row without
    the second upsert overwriting the first record's category.
    """

    dependencies = [
        ("listings", "0015_add_disclosure_record"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="disclosurerecord",
            unique_together={("company", "category", "pdf_url")},
        ),
    ]
