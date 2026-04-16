import django.db.models.deletion
import modelcluster.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0006_add_equity_detail_to_balancesheet'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeInfo',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('consolidated_headcount', models.IntegerField(blank=True, help_text='連結従業員数', null=True)),
                ('consolidated_temp_workers', models.IntegerField(blank=True, help_text='連結臨時従業員数（平均）', null=True)),
                ('headcount', models.IntegerField(blank=True, help_text='従業員数（単体）', null=True)),
                ('temp_workers', models.IntegerField(blank=True, help_text='臨時従業員数（単体平均）', null=True)),
                ('average_age', models.DecimalField(blank=True, decimal_places=1, help_text='平均年齢（歳）', max_digits=4, null=True)),
                ('average_tenure', models.DecimalField(blank=True, decimal_places=1, help_text='平均勤続年数（年）', max_digits=4, null=True)),
                ('average_salary', models.IntegerField(blank=True, help_text='平均年間給与（円）', null=True)),
                ('report', modelcluster.fields.ParentalKey(on_delete=django.db.models.deletion.CASCADE, related_name='employee_info', to='financials.financialreport')),
            ],
            options={
                'verbose_name': 'Employee Info',
            },
        ),
    ]
