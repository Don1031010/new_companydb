from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0008_add_forecast_models'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='forecastrecord',
            constraint=models.UniqueConstraint(
                condition=models.Q(source_report__isnull=False),
                fields=['source_report'],
                name='unique_forecast_per_report',
            ),
        ),
        migrations.AddConstraint(
            model_name='dividendforecast',
            constraint=models.UniqueConstraint(
                condition=models.Q(source_report__isnull=False),
                fields=['source_report'],
                name='unique_dividend_forecast_per_report',
            ),
        ),
    ]
