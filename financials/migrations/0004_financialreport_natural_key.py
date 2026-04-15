from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("financials", "0003_add_debt_components"),
    ]

    operations = [
        # Make edinet_doc_id nullable so TDnet-only records don't need it
        migrations.AlterField(
            model_name="financialreport",
            name="edinet_doc_id",
            field=models.CharField(
                blank=True,
                help_text="EDINET document ID, e.g. S100ABCD (null for TDnet-only records)",
                max_length=20,
                null=True,
                unique=True,
            ),
        ),
        # Add unique constraint on (company, fiscal_year, fiscal_quarter) as natural key
        migrations.AddConstraint(
            model_name="financialreport",
            constraint=models.UniqueConstraint(
                fields=["company", "fiscal_year", "fiscal_quarter"],
                name="unique_company_fiscal_year_quarter",
            ),
        ),
    ]
