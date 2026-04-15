from django.contrib import admin

from .models import FinancialReport, IncomeStatement, BalanceSheet, CashFlowStatement


class IncomeStatementInline(admin.StackedInline):
    model = IncomeStatement
    extra = 0


class BalanceSheetInline(admin.StackedInline):
    model = BalanceSheet
    extra = 0


class CashFlowStatementInline(admin.StackedInline):
    model = CashFlowStatement
    extra = 0


@admin.register(FinancialReport)
class FinancialReportAdmin(admin.ModelAdmin):
    list_display = ["company", "fiscal_year", "fiscal_quarter", "report_type", "is_consolidated", "period_end", "filed_at"]
    list_filter = ["report_type", "is_consolidated", "fiscal_year"]
    search_fields = ["company__stock_code", "company__name_ja", "edinet_doc_id"]
    inlines = [IncomeStatementInline, BalanceSheetInline, CashFlowStatementInline]
