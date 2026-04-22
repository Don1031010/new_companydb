from django.db import models
from modelcluster.fields import ParentalKey
from modelcluster.models import ClusterableModel


class FinancialReport(ClusterableModel):
    """
    Container for one filing (決算短信 or 有価証券報告書).
    Links a Company to its set of financial statements for a given period.
    """

    class ReportType(models.TextChoices):
        ANNUAL = "annual", "Annual (通期)"
        Q1 = "q1", "Q1 (第1四半期)"
        Q2 = "q2", "Q2 (第2四半期)"
        Q3 = "q3", "Q3 (第3四半期)"

    company = models.ForeignKey(
        "listings.Company",
        on_delete=models.CASCADE,
        related_name="financial_reports",
    )
    edinet_doc_id = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True,
        help_text="EDINET document ID, e.g. S100ABCD (null for TDnet-only records)",
    )
    period_end = models.DateField(help_text="Fiscal period end date (決算期末)")
    fiscal_year = models.PositiveSmallIntegerField(help_text="e.g. 2024 for FY2024")
    fiscal_quarter = models.PositiveSmallIntegerField(
        default=4,
        help_text="1–4; 4 = full year",
    )
    report_type = models.CharField(max_length=10, choices=ReportType.choices)
    is_consolidated = models.BooleanField(
        default=True,
        help_text="True = 連結; False = 単体",
    )
    filed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "fiscal_year", "fiscal_quarter"],
                name="unique_company_fiscal_year_quarter",
            ),
        ]
        indexes = [
            models.Index(fields=["company", "period_end"]),
            models.Index(fields=["fiscal_year", "fiscal_quarter"]),
        ]

    def __str__(self):
        return f"{self.company} {self.fiscal_year}Q{self.fiscal_quarter}"


class IncomeStatement(models.Model):
    """損益計算書 (P&L). All monetary values in JPY (thousands 千円)."""

    report = ParentalKey(
        FinancialReport,
        on_delete=models.CASCADE,
        related_name="income_statements",
    )
    # --- Top line ---
    revenue = models.BigIntegerField(null=True, blank=True, help_text="売上高")
    gross_profit = models.BigIntegerField(null=True, blank=True, help_text="売上総利益")

    # --- Operating ---
    operating_profit = models.BigIntegerField(null=True, blank=True, help_text="営業利益")
    operating_margin = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="営業利益率 (ratio, not %)",
    )

    # --- Recurring ---
    ordinary_profit = models.BigIntegerField(null=True, blank=True, help_text="経常利益")

    # --- Bottom line ---
    net_income = models.BigIntegerField(null=True, blank=True, help_text="親会社株主に帰属する当期純利益")
    eps = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="一株当たり当期純利益 (EPS)",
    )
    diluted_eps = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="希薄化後EPS",
    )
    roe = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="自己資本利益率 (ratio)",
    )

    # --- R&D ---
    rd_expenses = models.BigIntegerField(null=True, blank=True, help_text="研究開発費")

    # YoY change fields (useful for quick display, optional)
    revenue_yoy = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="Revenue YoY change (ratio)",
    )
    op_profit_yoy = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
    )

    class Meta:
        verbose_name = "Income Statement"

    def __str__(self):
        return f"P&L – {self.report}"


class BalanceSheet(models.Model):
    """貸借対照表 (B/S). All monetary values in JPY (thousands 千円)."""

    report = ParentalKey(
        FinancialReport,
        on_delete=models.CASCADE,
        related_name="balance_sheets",
    )
    # --- Assets ---
    total_assets = models.BigIntegerField(null=True, blank=True, help_text="総資産")
    current_assets = models.BigIntegerField(null=True, blank=True, help_text="流動資産")
    non_current_assets = models.BigIntegerField(null=True, blank=True, help_text="固定資産")
    cash_and_equivalents = models.BigIntegerField(null=True, blank=True, help_text="現金及び現金同等物")

    # --- Liabilities ---
    total_liabilities = models.BigIntegerField(null=True, blank=True, help_text="負債合計")
    current_liabilities = models.BigIntegerField(null=True, blank=True, help_text="流動負債")

    # --- Interest-bearing debt components ---
    short_term_loans = models.BigIntegerField(null=True, blank=True, help_text="短期借入金")
    commercial_paper = models.BigIntegerField(null=True, blank=True, help_text="コマーシャル・ペーパー")
    bonds_payable_current = models.BigIntegerField(null=True, blank=True, help_text="社債（流動）")
    long_term_loans = models.BigIntegerField(null=True, blank=True, help_text="長期借入金")
    bonds_payable = models.BigIntegerField(null=True, blank=True, help_text="社債（固定）")
    lease_obligations_current = models.BigIntegerField(null=True, blank=True, help_text="リース債務（流動）")
    lease_obligations_non_current = models.BigIntegerField(null=True, blank=True, help_text="リース債務（固定）")

    # --- Equity ---
    net_assets = models.BigIntegerField(null=True, blank=True, help_text="純資産合計")
    owners_equity = models.BigIntegerField(null=True, blank=True, help_text="自己資本")
    capital_stock = models.BigIntegerField(null=True, blank=True, help_text="資本金")
    retained_earnings = models.BigIntegerField(null=True, blank=True, help_text="利益剰余金")
    non_controlling_interests = models.BigIntegerField(null=True, blank=True, help_text="非支配株主持分")
    shares_issued = models.BigIntegerField(null=True, blank=True, help_text="発行済株式数（自己株式含む）")
    treasury_shares = models.BigIntegerField(null=True, blank=True, help_text="自己株式数")
    equity_ratio = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="自己資本比率 (ratio)",
    )
    book_value_per_share = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="一株当たり純資産 (BPS)",
    )

    @property
    def interest_bearing_debt(self):
        """
        有利子負債 = short_term_loans + commercial_paper + bonds_payable_current
                   + long_term_loans + bonds_payable
        Lease obligations excluded; add them manually if needed.
        Returns None if all components are null.
        """
        components = [
            self.short_term_loans,
            self.commercial_paper,
            self.bonds_payable_current,
            self.long_term_loans,
            self.bonds_payable,
        ]
        values = [v for v in components if v is not None]
        return sum(values) if values else None

    @property
    def interest_bearing_debt_incl_leases(self):
        """有利子負債（リース債務含む）"""
        base = self.interest_bearing_debt
        leases = [
            self.lease_obligations_current,
            self.lease_obligations_non_current,
        ]
        lease_total = sum(v for v in leases if v is not None)
        if base is None and lease_total == 0:
            return None
        return (base or 0) + lease_total

    class Meta:
        verbose_name = "Balance Sheet"

    def __str__(self):
        return f"B/S – {self.report}"


class ForecastRecord(models.Model):
    """
    業績予想 — one forecast snapshot as announced at a point in time.
    Never updated; a new row is inserted for every announcement so the full
    revision history is preserved.  PDF-only revised forecasts can be entered
    manually (source_report=None).
    Monetary values in JPY (同単位 as IncomeStatement).
    """

    company = models.ForeignKey(
        "listings.Company",
        on_delete=models.CASCADE,
        related_name="forecast_records",
    )
    announced_at = models.DateField(help_text="Announcement date (開示日)")
    source_report = models.ForeignKey(
        "FinancialReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forecasts",
        help_text="Quarterly report this forecast was published with (null for standalone revisions)",
    )
    target_fiscal_year = models.PositiveSmallIntegerField(help_text="e.g. 2025 for FY2025")
    target_fiscal_quarter = models.PositiveSmallIntegerField(
        default=4,
        help_text="1–4; 4 = full-year forecast",
    )

    # Forecast figures
    revenue = models.BigIntegerField(null=True, blank=True, help_text="売上高予想")
    operating_profit = models.BigIntegerField(null=True, blank=True, help_text="営業利益予想")
    ordinary_profit = models.BigIntegerField(null=True, blank=True, help_text="経常利益予想")
    net_income = models.BigIntegerField(null=True, blank=True, help_text="当期純利益予想")
    eps = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True, help_text="EPS予想"
    )
    revenue_yoy = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True, help_text="売上高増減率予想"
    )
    op_profit_yoy = models.DecimalField(
        max_digits=8, decimal_places=4, null=True, blank=True, help_text="営業利益増減率予想"
    )

    class Meta:
        ordering = ["-announced_at"]
        indexes = [
            models.Index(fields=["company", "target_fiscal_year", "-announced_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_report"],
                condition=models.Q(source_report__isnull=False),
                name="unique_forecast_per_report",
            ),
        ]

    def __str__(self):
        return f"{self.company} FY{self.target_fiscal_year}Q{self.target_fiscal_quarter} forecast @{self.announced_at}"


class DividendForecast(models.Model):
    """
    配当予想 — one dividend forecast snapshot.
    Never updated; insert a new row for each announcement.
    Values in JPY per share (円/株).
    """

    company = models.ForeignKey(
        "listings.Company",
        on_delete=models.CASCADE,
        related_name="dividend_forecasts",
    )
    announced_at = models.DateField(help_text="Announcement date (開示日)")
    source_report = models.ForeignKey(
        "FinancialReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dividend_forecasts",
        help_text="Quarterly report this forecast was published with (null for standalone revisions)",
    )
    target_fiscal_year = models.PositiveSmallIntegerField(help_text="e.g. 2025 for FY2025")

    # Forecasts (予想)
    interim_dividend = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="中間配当予想（円/株）"
    )
    year_end_dividend = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="期末配当予想（円/株）"
    )
    annual_dividend = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="年間配当予想（円/株）"
    )
    # Actuals — paid amounts confirmed in the same report (実績)
    interim_dividend_paid = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="中間配当実績（円/株）"
    )
    year_end_dividend_paid = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="期末配当実績（円/株）"
    )
    annual_dividend_paid = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True, help_text="年間配当実績（円/株）"
    )

    class Meta:
        ordering = ["-announced_at"]
        indexes = [
            models.Index(fields=["company", "target_fiscal_year", "-announced_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_report"],
                condition=models.Q(source_report__isnull=False),
                name="unique_dividend_forecast_per_report",
            ),
        ]

    def __str__(self):
        return f"{self.company} FY{self.target_fiscal_year} dividend forecast @{self.announced_at}"


class EmployeeInfo(models.Model):
    """従業員の状況. Only present in annual reports (有価証券報告書). Monetary values in JPY (円)."""

    report = ParentalKey(
        FinancialReport,
        on_delete=models.CASCADE,
        related_name="employee_info",
    )

    # --- Consolidated (連結) ---
    consolidated_headcount = models.IntegerField(null=True, blank=True, help_text="連結従業員数")
    consolidated_temp_workers = models.IntegerField(null=True, blank=True, help_text="連結臨時従業員数（平均）")

    # --- Non-consolidated / parent company (単体) ---
    headcount = models.IntegerField(null=True, blank=True, help_text="従業員数（単体）")
    temp_workers = models.IntegerField(null=True, blank=True, help_text="臨時従業員数（単体平均）")
    average_age = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, help_text="平均年齢（歳）"
    )
    average_tenure = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True, help_text="平均勤続年数（年）"
    )
    average_salary = models.IntegerField(null=True, blank=True, help_text="平均年間給与（円）")

    class Meta:
        verbose_name = "Employee Info"

    def __str__(self):
        return f"Employees – {self.report}"


class CashFlowStatement(models.Model):
    """キャッシュ・フロー計算書. All monetary values in JPY (thousands 千円)."""

    report = ParentalKey(
        FinancialReport,
        on_delete=models.CASCADE,
        related_name="cash_flow_statements",
    )
    operating_cf = models.BigIntegerField(
        null=True, blank=True, help_text="営業活動によるCF"
    )
    investing_cf = models.BigIntegerField(
        null=True, blank=True, help_text="投資活動によるCF"
    )
    financing_cf = models.BigIntegerField(
        null=True, blank=True, help_text="財務活動によるCF"
    )
    capex = models.BigIntegerField(
        null=True, blank=True,
        help_text="設備投資額（設備投資等の概要より、正値）",
    )
    depreciation = models.BigIntegerField(
        null=True, blank=True,
        help_text="減価償却費",
    )

    @property
    def free_cash_flow(self):
        """FCF = operating CF - capex (capex is a positive figure from 設備投資等の概要)."""
        if self.operating_cf is not None and self.capex is not None:
            return self.operating_cf - self.capex
        return None

    class Meta:
        verbose_name = "Cash Flow Statement"

    def __str__(self):
        return f"CF – {self.report}"
