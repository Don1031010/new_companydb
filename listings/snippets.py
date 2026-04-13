"""
snippets.py — Register Company and StockExchange as Wagtail Snippets
with search, filtering, and column configuration.
"""

from django.utils.html import format_html, mark_safe
from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.ui.tables import Column, BooleanColumn

from .models import Company, StockExchange, Shareholder, Institution, DisclosureRecord


class ResourceLinksColumn(Column):
    """Renders compact clickable links for the disclosure document URLs."""

    def get_value(self, instance):
        links = []
        if instance.pdf_url:
            links.append(format_html(
                '<a href="{}" target="_blank" rel="noopener">PDF</a>', instance.pdf_url
            ))
        if instance.xbrl_url:
            links.append(format_html(
                '<a href="{}" target="_blank" rel="noopener">XBRL</a>', instance.xbrl_url
            ))
        if instance.html_summary_url:
            links.append(format_html(
                '<a href="{}" target="_blank" rel="noopener">HTML</a>', instance.html_summary_url
            ))
        if instance.html_attachment_url:
            links.append(format_html(
                '<a href="{}" target="_blank" rel="noopener">添付</a>', instance.html_attachment_url
            ))
        return mark_safe(' &nbsp;·&nbsp; '.join(str(l) for l in links))


class StockExchangeViewSet(SnippetViewSet):
    model = StockExchange
    menu_label = "証券取引所"
    icon = "site"
    list_display = ["code", "name_ja", "short_name", "website"]
    search_fields = ["code", "name_ja", "name_en", "short_name"]


class CompanyViewSet(SnippetViewSet):
    model = Company
    menu_label = "上場会社"
    icon = "group"
    list_display = [
        "stock_code",
        "name_ja",
        "name_en",
        Column("get_industry_33_display", label="業種"),
        Column("status", label="ステータス"),
        BooleanColumn("is_non_jpx", label="東証非上場"),
    ]
    list_filter = ["status", "industry_33", "is_foreign", "is_non_jpx"]
    search_fields = ["stock_code", "name_ja", "name_kana", "name_en"]
    ordering = ["stock_code"]


class InstitutionViewSet(SnippetViewSet):
    model = Institution
    menu_label = "親機関"
    icon = "group"
    list_display = ["name", "name_en", "name_zh"]
    search_fields = ["name", "name_en", "name_zh"]
    ordering = ["name"]


class ShareholderViewSet(SnippetViewSet):
    model = Shareholder
    menu_label = "株主"
    icon = "user"
    list_display = ["name", "institution", "address"]
    search_fields = ["name", "address"]
    list_filter = ["institution"]
    ordering = ["name"]


class DisclosureRecordViewSet(SnippetViewSet):
    model = DisclosureRecord
    menu_label = "適時開示"
    icon = "doc-full"
    list_display = [
        Column("company", label="会社"),
        Column("disclosed_date", label="開示日"),
        "title",
        ResourceLinksColumn("links", label="資料"),
    ]
    list_filter = ["disclosed_date"]
    search_fields = ["title", "company__stock_code", "company__name_ja"]
    ordering = ["company__stock_code", "-disclosed_date"]


class ListedCompaniesGroup(SnippetViewSetGroup):
    """Groups Exchange + Company + Institution + Shareholder under one admin menu section."""
    menu_label = "上場会社情報"
    menu_icon = "chart-line"
    menu_order = 200
    items = [StockExchangeViewSet, CompanyViewSet, InstitutionViewSet, ShareholderViewSet, DisclosureRecordViewSet]
