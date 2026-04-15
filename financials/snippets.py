"""
snippets.py — Register financial statement models as Wagtail Snippets.
"""

from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup
from wagtail.admin.panels import (
    FieldPanel, FieldRowPanel, InlinePanel, MultiFieldPanel, ObjectList, TabbedInterface,
)
from wagtail.admin.ui.tables import Column, TitleColumn

from .models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement


class FinancialReportViewSet(SnippetViewSet):
    model = FinancialReport
    menu_label = "決算報告"
    icon = "doc-full-inverse"
    list_display = [
        TitleColumn("__str__", label="レポート", url_name="wagtailsnippets_financials_financialreport:edit", sort_key="company__name_ja"),
        Column("fiscal_year", label="年度", sort_key="fiscal_year"),
        Column("fiscal_quarter", label="Q", sort_key="fiscal_quarter"),
        Column("report_type", label="種別"),
        Column("period_end", label="決算期末", sort_key="period_end"),
        Column("is_consolidated", label="連結"),
    ]
    list_filter = ["report_type", "is_consolidated", "fiscal_year"]
    search_fields = ["company__stock_code", "company__name_ja", "edinet_doc_id"]
    ordering = ["-fiscal_year", "-fiscal_quarter", "company__name_ja"]

    panels = [
        MultiFieldPanel([
            FieldPanel("company"),
            FieldRowPanel([
                FieldPanel("fiscal_year"),
                FieldPanel("fiscal_quarter"),
                FieldPanel("report_type"),
            ]),
            FieldRowPanel([
                FieldPanel("period_end"),
                FieldPanel("filed_at"),
                FieldPanel("is_consolidated"),
            ]),
            FieldPanel("edinet_doc_id"),
        ], heading="基本情報"),

        InlinePanel("income_statements", heading="損益計算書 (P&L)", max_num=1, panels=[
            FieldRowPanel([
                FieldPanel("revenue"),
                FieldPanel("gross_profit"),
            ]),
            FieldRowPanel([
                FieldPanel("operating_profit"),
                FieldPanel("operating_margin"),
                FieldPanel("ordinary_profit"),
            ]),
            FieldRowPanel([
                FieldPanel("net_income"),
                FieldPanel("eps"),
                FieldPanel("diluted_eps"),
                FieldPanel("roe"),
            ]),
            FieldPanel("rd_expenses"),
            FieldRowPanel([
                FieldPanel("revenue_yoy"),
                FieldPanel("op_profit_yoy"),
            ]),
        ]),

        InlinePanel("balance_sheets", heading="貸借対照表 (B/S)", max_num=1, panels=[
            FieldRowPanel([
                FieldPanel("total_assets"),
                FieldPanel("current_assets"),
                FieldPanel("non_current_assets"),
                FieldPanel("cash_and_equivalents"),
            ]),
            FieldRowPanel([
                FieldPanel("total_liabilities"),
                FieldPanel("current_liabilities"),
            ]),
            MultiFieldPanel([
                FieldRowPanel([
                    FieldPanel("short_term_loans"),
                    FieldPanel("commercial_paper"),
                    FieldPanel("bonds_payable_current"),
                ]),
                FieldRowPanel([
                    FieldPanel("long_term_loans"),
                    FieldPanel("bonds_payable"),
                ]),
                FieldRowPanel([
                    FieldPanel("lease_obligations_current"),
                    FieldPanel("lease_obligations_non_current"),
                ]),
            ], heading="有利子負債明細"),
            FieldRowPanel([
                FieldPanel("net_assets"),
                FieldPanel("shareholders_equity"),
                FieldPanel("equity_ratio"),
                FieldPanel("book_value_per_share"),
            ]),
        ]),

        InlinePanel("cash_flow_statements", heading="CF計算書", max_num=1, panels=[
            FieldRowPanel([
                FieldPanel("operating_cf"),
                FieldPanel("investing_cf"),
                FieldPanel("financing_cf"),
            ]),
            FieldRowPanel([
                FieldPanel("capex"),
                FieldPanel("depreciation"),
            ]),
        ]),
    ]


class IncomeStatementViewSet(SnippetViewSet):
    model = IncomeStatement
    menu_label = "損益計算書"
    icon = "list-ul"
    list_display = [
        TitleColumn("report", label="報告", url_name="wagtailsnippets_financials_incomestatement:edit"),
        Column("revenue", label="売上高"),
        Column("operating_profit", label="営業利益"),
        Column("ordinary_profit", label="経常利益"),
        Column("net_income", label="当期純利益"),
        Column("eps", label="EPS"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]
    panels = [
        FieldPanel("report"),
        FieldRowPanel([FieldPanel("revenue"), FieldPanel("gross_profit")]),
        FieldRowPanel([
            FieldPanel("operating_profit"),
            FieldPanel("operating_margin"),
            FieldPanel("ordinary_profit"),
        ]),
        FieldRowPanel([
            FieldPanel("net_income"),
            FieldPanel("eps"),
            FieldPanel("diluted_eps"),
            FieldPanel("roe"),
        ]),
        FieldPanel("rd_expenses"),
        FieldRowPanel([FieldPanel("revenue_yoy"), FieldPanel("op_profit_yoy")]),
    ]


class BalanceSheetViewSet(SnippetViewSet):
    model = BalanceSheet
    menu_label = "貸借対照表"
    icon = "list-ul"
    list_display = [
        TitleColumn("report", label="報告", url_name="wagtailsnippets_financials_balancesheet:edit"),
        Column("total_assets", label="総資産"),
        Column("net_assets", label="純資産"),
        Column("equity_ratio", label="自己資本比率"),
        Column("cash_and_equivalents", label="現金"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]
    panels = [
        FieldPanel("report"),
        FieldRowPanel([
            FieldPanel("total_assets"),
            FieldPanel("current_assets"),
            FieldPanel("non_current_assets"),
            FieldPanel("cash_and_equivalents"),
        ]),
        FieldRowPanel([FieldPanel("total_liabilities"), FieldPanel("current_liabilities")]),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("short_term_loans"),
                FieldPanel("commercial_paper"),
                FieldPanel("bonds_payable_current"),
            ]),
            FieldRowPanel([FieldPanel("long_term_loans"), FieldPanel("bonds_payable")]),
            FieldRowPanel([
                FieldPanel("lease_obligations_current"),
                FieldPanel("lease_obligations_non_current"),
            ]),
        ], heading="有利子負債明細"),
        FieldRowPanel([
            FieldPanel("net_assets"),
            FieldPanel("shareholders_equity"),
            FieldPanel("equity_ratio"),
            FieldPanel("book_value_per_share"),
        ]),
    ]


class CashFlowStatementViewSet(SnippetViewSet):
    model = CashFlowStatement
    menu_label = "CF計算書"
    icon = "list-ul"
    list_display = [
        TitleColumn("report", label="報告", url_name="wagtailsnippets_financials_cashflowstatement:edit"),
        Column("operating_cf", label="営業CF"),
        Column("investing_cf", label="投資CF"),
        Column("financing_cf", label="財務CF"),
        Column("capex", label="設備投資"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]
    panels = [
        FieldPanel("report"),
        FieldRowPanel([
            FieldPanel("operating_cf"),
            FieldPanel("investing_cf"),
            FieldPanel("financing_cf"),
        ]),
        FieldRowPanel([FieldPanel("capex"), FieldPanel("depreciation")]),
    ]


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
