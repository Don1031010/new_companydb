"""
snippets.py — Register financial statement models as Wagtail Snippets.
"""

from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup, CreateView
from wagtail.admin.panels import (
    FieldPanel, FieldRowPanel, InlinePanel, MultiFieldPanel, ObjectList, TabbedInterface,
)
from wagtail.admin.ui.tables import Column, TitleColumn

from .models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement, EmployeeInfo, ForecastRecord, DividendForecast


class CompanyPrefillMixin:
    """Populate the company field from ?company=<pk> on the add form."""
    def get_initial(self):
        initial = super().get_initial()
        company_pk = self.request.GET.get("company")
        if company_pk:
            initial["company"] = company_pk
        return initial


class ForecastRecordCreateView(CompanyPrefillMixin, CreateView):
    pass


class DividendForecastCreateView(CompanyPrefillMixin, CreateView):
    pass


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
                FieldPanel("owners_equity"),
                FieldPanel("equity_ratio"),
                FieldPanel("book_value_per_share"),
            ]),
            FieldRowPanel([
                FieldPanel("capital_stock"),
                FieldPanel("retained_earnings"),
                FieldPanel("non_controlling_interests"),
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

        InlinePanel("employee_info", heading="従業員の状況", max_num=1, panels=[
            MultiFieldPanel([
                FieldRowPanel([
                    FieldPanel("consolidated_headcount"),
                    FieldPanel("consolidated_temp_workers"),
                ]),
            ], heading="連結"),
            MultiFieldPanel([
                FieldRowPanel([
                    FieldPanel("headcount"),
                    FieldPanel("temp_workers"),
                ]),
                FieldRowPanel([
                    FieldPanel("average_age"),
                    FieldPanel("average_tenure"),
                    FieldPanel("average_salary"),
                ]),
            ], heading="単体"),
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
            FieldPanel("owners_equity"),
            FieldPanel("equity_ratio"),
            FieldPanel("book_value_per_share"),
        ]),
        FieldRowPanel([
            FieldPanel("capital_stock"),
            FieldPanel("retained_earnings"),
            FieldPanel("non_controlling_interests"),
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


class EmployeeInfoViewSet(SnippetViewSet):
    model = EmployeeInfo
    menu_label = "従業員状況"
    icon = "group"
    list_display = [
        TitleColumn("report", label="報告", url_name="wagtailsnippets_financials_employeeinfo:edit"),
        Column("consolidated_headcount", label="連結人数"),
        Column("headcount", label="単体人数"),
        Column("average_age", label="平均年齢"),
        Column("average_tenure", label="平均勤続"),
        Column("average_salary", label="平均給与"),
    ]
    search_fields = ["report__company__stock_code", "report__company__name_ja"]
    ordering = ["-report__period_end"]
    panels = [
        FieldPanel("report"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("consolidated_headcount"),
                FieldPanel("consolidated_temp_workers"),
            ]),
        ], heading="連結"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("headcount"),
                FieldPanel("temp_workers"),
            ]),
            FieldRowPanel([
                FieldPanel("average_age"),
                FieldPanel("average_tenure"),
                FieldPanel("average_salary"),
            ]),
        ], heading="単体"),
    ]


class ForecastRecordViewSet(SnippetViewSet):
    model = ForecastRecord
    menu_label = "業績予想"
    icon = "pick"
    add_view_class = ForecastRecordCreateView
    list_display = [
        TitleColumn("__str__", label="予想", url_name="wagtailsnippets_financials_forecastrecord:edit"),
        Column("announced_at", label="開示日"),
        Column("target_fiscal_year", label="対象年度"),
        Column("revenue", label="売上高予想"),
        Column("operating_profit", label="営業利益予想"),
        Column("net_income", label="純利益予想"),
        Column("eps", label="EPS予想"),
    ]
    search_fields = ["company__stock_code", "company__name_ja"]
    ordering = ["-announced_at"]
    panels = [
        FieldRowPanel([
            FieldPanel("company"),
            FieldPanel("announced_at"),
        ]),
        FieldRowPanel([
            FieldPanel("target_fiscal_year"),
            FieldPanel("target_fiscal_quarter"),
            FieldPanel("source_report"),
        ]),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("revenue"),
                FieldPanel("operating_profit"),
                FieldPanel("ordinary_profit"),
            ]),
            FieldRowPanel([
                FieldPanel("net_income"),
                FieldPanel("eps"),
            ]),
            FieldRowPanel([
                FieldPanel("revenue_yoy"),
                FieldPanel("op_profit_yoy"),
            ]),
        ], heading="予想数値"),
    ]


class DividendForecastViewSet(SnippetViewSet):
    model = DividendForecast
    menu_label = "配当予想"
    icon = "pick"
    add_view_class = DividendForecastCreateView
    list_display = [
        TitleColumn("__str__", label="予想", url_name="wagtailsnippets_financials_dividendforecast:edit"),
        Column("announced_at", label="開示日"),
        Column("target_fiscal_year", label="対象年度"),
        Column("interim_dividend_paid", label="中間(実)"),
        Column("interim_dividend", label="中間(予)"),
        Column("year_end_dividend", label="期末(予)"),
        Column("annual_dividend", label="年間(予)"),
    ]
    search_fields = ["company__stock_code", "company__name_ja"]
    ordering = ["-announced_at"]
    panels = [
        FieldRowPanel([
            FieldPanel("company"),
            FieldPanel("announced_at"),
        ]),
        FieldRowPanel([
            FieldPanel("target_fiscal_year"),
            FieldPanel("source_report"),
        ]),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("interim_dividend"),
                FieldPanel("year_end_dividend"),
                FieldPanel("annual_dividend"),
            ]),
        ], heading="配当予想（円/株）"),
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("interim_dividend_paid"),
                FieldPanel("year_end_dividend_paid"),
                FieldPanel("annual_dividend_paid"),
            ]),
        ], heading="配当実績（円/株）"),
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
        EmployeeInfoViewSet,
        ForecastRecordViewSet,
        DividendForecastViewSet,
    ]
