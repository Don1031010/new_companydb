from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Drop the category field from DisclosureRecord and revert unique_together
    to (company, pdf_url).

    Both 決算情報 (1101) and 決定事実/発生事実 (1102) rows are now stored in a
    single flat list deduplicated by pdf_url. The 1101 version always wins when
    the same document appears in both tables.
    """

    dependencies = [
        ("listings", "0016_disclosurerecord_unique_category"),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name="disclosurerecord",
            unique_together={("company", "pdf_url")},
        ),
        migrations.RemoveField(
            model_name="disclosurerecord",
            name="category",
        ),
    ]
