from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0009_forecast_unique_per_report'),
    ]

    operations = [
        migrations.AddField(
            model_name='dividendforecast',
            name='interim_dividend_paid',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='中間配当実績（円/株）', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='dividendforecast',
            name='year_end_dividend_paid',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='期末配当実績（円/株）', max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='dividendforecast',
            name='annual_dividend_paid',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='年間配当実績（円/株）', max_digits=10, null=True),
        ),
    ]
