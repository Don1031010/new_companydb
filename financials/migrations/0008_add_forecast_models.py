import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0007_add_employee_info'),
        ('listings', '0020_alter_disclosurerecord_options_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='ForecastRecord',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('announced_at', models.DateField(help_text='Announcement date (開示日)')),
                ('target_fiscal_year', models.PositiveSmallIntegerField(help_text='e.g. 2025 for FY2025')),
                ('target_fiscal_quarter', models.PositiveSmallIntegerField(default=4, help_text='1–4; 4 = full-year forecast')),
                ('revenue', models.BigIntegerField(blank=True, help_text='売上高予想', null=True)),
                ('operating_profit', models.BigIntegerField(blank=True, help_text='営業利益予想', null=True)),
                ('ordinary_profit', models.BigIntegerField(blank=True, help_text='経常利益予想', null=True)),
                ('net_income', models.BigIntegerField(blank=True, help_text='当期純利益予想', null=True)),
                ('eps', models.DecimalField(blank=True, decimal_places=2, help_text='EPS予想', max_digits=12, null=True)),
                ('revenue_yoy', models.DecimalField(blank=True, decimal_places=4, help_text='売上高増減率予想', max_digits=8, null=True)),
                ('op_profit_yoy', models.DecimalField(blank=True, decimal_places=4, help_text='営業利益増減率予想', max_digits=8, null=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='forecast_records', to='listings.company')),
                ('source_report', models.ForeignKey(blank=True, help_text='Quarterly report this forecast was published with (null for standalone revisions)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='forecasts', to='financials.financialreport')),
            ],
            options={
                'ordering': ['-announced_at'],
            },
        ),
        migrations.AddIndex(
            model_name='forecastrecord',
            index=models.Index(fields=['company', 'target_fiscal_year', '-announced_at'], name='fin_forecast_company_fy_idx'),
        ),
        migrations.CreateModel(
            name='DividendForecast',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('announced_at', models.DateField(help_text='Announcement date (開示日)')),
                ('target_fiscal_year', models.PositiveSmallIntegerField(help_text='e.g. 2025 for FY2025')),
                ('interim_dividend', models.DecimalField(blank=True, decimal_places=2, help_text='中間配当予想（円/株）', max_digits=10, null=True)),
                ('year_end_dividend', models.DecimalField(blank=True, decimal_places=2, help_text='期末配当予想（円/株）', max_digits=10, null=True)),
                ('annual_dividend', models.DecimalField(blank=True, decimal_places=2, help_text='年間配当予想（円/株）', max_digits=10, null=True)),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dividend_forecasts', to='listings.company')),
                ('source_report', models.ForeignKey(blank=True, help_text='Quarterly report this forecast was published with (null for standalone revisions)', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='dividend_forecasts', to='financials.financialreport')),
            ],
            options={
                'ordering': ['-announced_at'],
            },
        ),
        migrations.AddIndex(
            model_name='dividendforecast',
            index=models.Index(fields=['company', 'target_fiscal_year', '-announced_at'], name='fin_divforecast_company_fy_idx'),
        ),
    ]
