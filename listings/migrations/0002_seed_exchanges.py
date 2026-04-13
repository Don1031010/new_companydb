"""
Data migration: seed the five Japanese stock exchanges.
Run after: python manage.py makemigrations && python manage.py migrate
"""

from django.db import migrations


EXCHANGES = [
    {
        "code": "TSE",
        "name_ja": "東京証券取引所",
        "name_en": "Tokyo Stock Exchange",
        "short_name": "東証",
        "website": "https://www.jpx.co.jp/",
    },
    {
        "code": "NSE",
        "name_ja": "名古屋証券取引所",
        "name_en": "Nagoya Stock Exchange",
        "short_name": "名証",
        "website": "https://www.nse.or.jp/",
    },
    {
        "code": "SSE",
        "name_ja": "札幌証券取引所",
        "name_en": "Sapporo Securities Exchange",
        "short_name": "札証",
        "website": "https://www.sse.or.jp/",
    },
    {
        "code": "FSE",
        "name_ja": "福岡証券取引所",
        "name_en": "Fukuoka Stock Exchange",
        "short_name": "福証",
        "website": "https://www.fse.or.jp/",
    },
]


def seed_exchanges(apps, schema_editor):
    StockExchange = apps.get_model("listings", "StockExchange")
    for data in EXCHANGES:
        StockExchange.objects.get_or_create(code=data["code"], defaults=data)


def unseed_exchanges(apps, schema_editor):
    StockExchange = apps.get_model("listings", "StockExchange")
    StockExchange.objects.filter(code__in=[e["code"] for e in EXCHANGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        # Replace with your actual last migration name
        ("listings", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_exchanges, reverse_code=unseed_exchanges),
    ]
