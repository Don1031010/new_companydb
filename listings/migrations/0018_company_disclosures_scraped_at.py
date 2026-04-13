from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0017_disclosurerecord_remove_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="disclosures_scraped_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                verbose_name="適時開示取得日時",
                help_text="適時開示情報を最後に取得した日時",
            ),
        ),
    ]
