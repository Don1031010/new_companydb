from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("listings", "0014_add_edinet_document"),
    ]

    operations = [
        migrations.CreateModel(
            name="DisclosureRecord",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("category", models.CharField(
                    choices=[("earnings", "決算情報"), ("material_fact", "決定事実・発生事実")],
                    db_index=True,
                    max_length=20,
                    verbose_name="区分",
                )),
                ("disclosed_date", models.DateField(db_index=True, verbose_name="開示日")),
                ("title", models.CharField(max_length=500, verbose_name="表題")),
                ("pdf_url", models.URLField(blank=True, max_length=500, verbose_name="PDF")),
                ("xbrl_url", models.URLField(blank=True, max_length=500, verbose_name="XBRL")),
                ("html_summary_url", models.URLField(blank=True, max_length=500, verbose_name="HTML（サマリー）")),
                ("html_attachment_url", models.URLField(blank=True, max_length=500, verbose_name="HTML（添付）")),
                ("scraped_at", models.DateTimeField(auto_now=True, verbose_name="取得日時")),
                ("company", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="disclosures",
                    to="listings.company",
                    verbose_name="会社",
                )),
            ],
            options={
                "verbose_name": "適時開示",
                "verbose_name_plural": "適時開示",
                "ordering": ["-disclosed_date", "company"],
            },
        ),
        migrations.AddIndex(
            model_name="disclosurerecord",
            index=models.Index(fields=["company", "-disclosed_date"], name="listings_di_company_date_idx"),
        ),
        migrations.AlterUniqueTogether(
            name="disclosurerecord",
            unique_together={("company", "pdf_url")},
        ),
    ]
