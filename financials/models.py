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
    shareholders_equity = models.BigIntegerField(null=True, blank=True, help_text="株主資本")
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
