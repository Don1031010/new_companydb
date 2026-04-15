"""
snippets.py — Register financial statement models as Wagtail Snippets.
"""

from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.ui.tables import Column

from .models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement


class FinancialReportViewSet(SnippetViewSet):
    model = FinancialReport
    menu_label = "決算報告"
    icon = "doc-full-inverse"
    list_display = [
        Column("company", label="会社"),
        Column("fiscal_year", label="年度"),
        Column("fiscal_quarter", label="Q"),
        Column("report_type", label="種別"),
        Column("period_end", label="決算期末"),
        Column("is_consolidated", label="連結"),
    ]
    list_filter = ["report_type", "is_consolidated", "fiscal_year"]
    search_fields = ["company__stock_code", "company__name_ja", "edinet_doc_id"]
    ordering = ["-period_end"]


class IncomeStatementViewSet(SnippetViewSet):
    model = IncomeStatement
    menu_label = "損益計算書"
    icon = "list-ul"
    list_display = [
        Column("report", label="報告"),
        Column("revenue", label="売上高"),
        Column("operating_profit", label="営業利益"),
        Column("ordinary_profit", label="経常利益"),
        Column("net_income", label="当期純利益"),
        Column("eps", label="EPS"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]


class BalanceSheetViewSet(SnippetViewSet):
    model = BalanceSheet
    menu_label = "貸借対照表"
    icon = "list-ul"
    list_display = [
        Column("report", label="報告"),
        Column("total_assets", label="総資産"),
        Column("net_assets", label="純資産"),
        Column("equity_ratio", label="自己資本比率"),
        Column("cash_and_equivalents", label="現金"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]


class CashFlowStatementViewSet(SnippetViewSet):
    model = CashFlowStatement
    menu_label = "CF計算書"
    icon = "list-ul"
    list_display = [
        Column("report", label="報告"),
        Column("operating_cf", label="営業CF"),
        Column("investing_cf", label="投資CF"),
        Column("financing_cf", label="財務CF"),
        Column("capex", label="設備投資"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]


class FinancialsGroup(SnippetViewSetGroup):
    menu_label = "財務情報"
    menu_icon = "chart-line"
    menu_order = 250
    items = [
        FinancialReportViewSet,
        IncomeStatementViewSet,
        BalanceSheetViewSet,
        CashFlowStatementViewSet,
    ]
