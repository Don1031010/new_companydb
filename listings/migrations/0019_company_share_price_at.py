from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0018_company_disclosures_scraped_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="share_price_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="株価時刻"),
        ),
    ]
