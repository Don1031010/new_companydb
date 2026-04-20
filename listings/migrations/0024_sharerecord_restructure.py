import django.db.models.deletion
from django.db import migrations, models
from collections import defaultdict


def migrate_shareholder_data(apps, schema_editor):
    """
    For each unique (company, as_of_date) group in ShareRecord:
      - keep the first row as the snapshot
      - create MajorShareholder entries from all rows in the group
      - delete the duplicate rows
    """
    ShareRecord = apps.get_model('listings', 'ShareRecord')
    MajorShareholder = apps.get_model('listings', 'MajorShareholder')

    groups = defaultdict(list)
    for sr in ShareRecord.objects.order_by('company_id', 'as_of_date', 'rank'):
        groups[(sr.company_id, sr.as_of_date)].append(sr)

    for rows in groups.values():
        snapshot = rows[0]
        entries = [
            MajorShareholder(
                share_record_id=snapshot.id,
                shareholder_id=sr.shareholder_id,
                rank=sr.rank,
                shares=sr.shares,
                percentage=sr.percentage,
            )
            for sr in rows
        ]
        MajorShareholder.objects.bulk_create(entries)

        extra_ids = [sr.id for sr in rows[1:]]
        if extra_ids:
            ShareRecord.objects.filter(id__in=extra_ids).delete()


def reverse_migrate(apps, schema_editor):
    MajorShareholder = apps.get_model('listings', 'MajorShareholder')
    MajorShareholder.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('listings', '0023_sharerecord_history'),
    ]

    operations = [
        # 1. Meta-only change
        migrations.AlterModelOptions(
            name='sharerecord',
            options={
                'ordering': ['company', '-as_of_date'],
                'verbose_name': '株主情報スナップショット',
                'verbose_name_plural': '株主情報スナップショット',
            },
        ),

        # 2. Add new fields to ShareRecord
        migrations.AddField(
            model_name='sharerecord',
            name='edinet_doc',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='share_records',
                to='listings.edinetdocument',
                verbose_name='EDINETドキュメント',
            ),
        ),
        migrations.AddField(
            model_name='sharerecord',
            name='total_shares',
            field=models.BigIntegerField(blank=True, null=True, verbose_name='発行済株式数'),
        ),
        migrations.AddField(
            model_name='sharerecord',
            name='treasury_shares',
            field=models.BigIntegerField(blank=True, null=True, verbose_name='自己株式数'),
        ),
        migrations.AlterField(
            model_name='sharerecord',
            name='as_of_date',
            field=models.DateField(blank=True, null=True, verbose_name='基準日'),
        ),

        # 3. Create MajorShareholder before data migration
        migrations.CreateModel(
            name='MajorShareholder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('rank', models.PositiveSmallIntegerField(verbose_name='順位')),
                ('shares', models.BigIntegerField(blank=True, null=True, verbose_name='保有株数（株）')),
                ('percentage', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True, verbose_name='持株比率（%）')),
                ('share_record', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='entries',
                    to='listings.sharerecord',
                    verbose_name='スナップショット',
                )),
                ('shareholder', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name='holdings',
                    to='listings.shareholder',
                    verbose_name='株主',
                )),
            ],
            options={
                'verbose_name': '大株主',
                'verbose_name_plural': '大株主',
                'ordering': ['share_record', 'rank'],
                'unique_together': {('share_record', 'rank')},
            },
        ),

        # 4. Data migration: move per-entry data into MajorShareholder, deduplicate ShareRecord
        migrations.RunPython(migrate_shareholder_data, reverse_migrate),

        # 5. Now safe to enforce (company, as_of_date) uniqueness
        migrations.AlterUniqueTogether(
            name='sharerecord',
            unique_together={('company', 'as_of_date')},
        ),

        # 6. Drop old per-entry fields from ShareRecord
        migrations.RemoveField(model_name='sharerecord', name='percentage'),
        migrations.RemoveField(model_name='sharerecord', name='rank'),
        migrations.RemoveField(model_name='sharerecord', name='shareholder'),
        migrations.RemoveField(model_name='sharerecord', name='shares'),

        # 7. Add CompanyShareInfo
        migrations.CreateModel(
            name='CompanyShareInfo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('as_of_date', models.DateField(verbose_name='基準日')),
                ('source', models.CharField(
                    choices=[
                        ('tanshin_q1', '第1四半期決算短信'),
                        ('tanshin_q2', '第2四半期決算短信'),
                        ('tanshin_q3', '第3四半期決算短信'),
                        ('tanshin_q4', '通期決算短信'),
                        ('edinet_interim', '半期報告書（EDINET）'),
                        ('edinet_annual', '有価証券報告書（EDINET）'),
                    ],
                    max_length=20,
                    verbose_name='データソース',
                )),
                ('total_shares', models.BigIntegerField(blank=True, null=True, verbose_name='発行済株式数')),
                ('treasury_shares', models.BigIntegerField(blank=True, null=True, verbose_name='自己株式数')),
                ('average_total_shares', models.BigIntegerField(blank=True, null=True, verbose_name='平均発行済株式数')),
                ('company', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='share_info',
                    to='listings.company',
                    verbose_name='会社',
                )),
            ],
            options={
                'verbose_name': '株式数推移',
                'verbose_name_plural': '株式数推移',
                'ordering': ['company', '-as_of_date'],
                'unique_together': {('company', 'as_of_date')},
            },
        ),

        # 8. Remove treasury_shares from Company
        migrations.RemoveField(model_name='company', name='treasury_shares'),
    ]
