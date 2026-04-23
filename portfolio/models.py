from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models

from listings.models import Company


TRANSACTION_TYPE_CHOICES = [
    ("buy",        "現物買い"),
    ("sell",       "現物売り"),
    ("dividend",   "配当金"),
    ("fee",        "手数料・税"),
    ("deposit",    "入金"),
    ("withdrawal", "出金"),
]

ASSET_TYPE_CHOICES = [
    ("cash_stock", "現物株"),
    ("margin",     "信用取引"),
    ("cfd",        "CFD"),
    ("fx",         "FX"),
    ("cash",       "現金"),
]

TRANSACTION_ASSET_MAP = {
    "buy":        "cash_stock",
    "sell":       "cash_stock",
    "dividend":   "cash_stock",
    "fee":        "cash",
    "deposit":    "cash",
    "withdrawal": "cash",
}

ACCOUNT_TYPE_CHOICES = [
    ("tokutei",        "特定口座"),
    ("ippan",          "一般口座"),
    ("nisa_growth",    "NISA成長投資枠"),
    ("nisa_tsumitate", "NISAつみたて枠"),
]

NISA_ACCOUNT_TYPES = {"nisa_growth", "nisa_tsumitate"}

NISA_ANNUAL_LIMITS = {
    "nisa_growth":    2_400_000,
    "nisa_tsumitate": 1_200_000,
}

BROKER_TYPE_CHOICES = [
    ("securities", "証券会社"),
    ("cfd",        "CFD業者"),
    ("fx",         "FX業者"),
]


class Broker(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="brokers")
    name = models.CharField(max_length=100, verbose_name="ブローカー名")
    broker_type = models.CharField(max_length=20, choices=BROKER_TYPE_CHOICES, default="securities", verbose_name="種別")
    notes = models.TextField(blank=True, verbose_name="備考")

    class Meta:
        ordering = ["name"]
        verbose_name = "ブローカー"
        verbose_name_plural = "ブローカー"

    def __str__(self):
        return self.name


class Transaction(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="transactions")
    broker = models.ForeignKey(Broker, on_delete=models.PROTECT, null=True, blank=True,
                               related_name="transactions", verbose_name="ブローカー")
    date = models.DateField(verbose_name="取引日")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES, verbose_name="取引種別")
    asset_type = models.CharField(max_length=20, choices=ASSET_TYPE_CHOICES, default="cash_stock", verbose_name="資産種別")

    # Instrument — company FK for listed stocks, free symbol for everything else
    company = models.ForeignKey(Company, on_delete=models.PROTECT, null=True, blank=True,
                                related_name="portfolio_transactions", verbose_name="銘柄")
    symbol = models.CharField(max_length=30, blank=True, verbose_name="シンボル")

    # Trade fields (buy / sell)
    quantity = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name="数量")
    price = models.DecimalField(max_digits=15, decimal_places=4, null=True, blank=True, verbose_name="単価")
    fees = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="手数料")
    taxes = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"), verbose_name="税金")

    # Amount field — used for dividend / fee / deposit / withdrawal
    amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, verbose_name="金額")

    currency = models.CharField(max_length=3, default="JPY", verbose_name="通貨")
    fx_rate = models.DecimalField(max_digits=12, decimal_places=6, default=Decimal("1"), verbose_name="為替レート")

    account_type = models.CharField(
        max_length=20, choices=ACCOUNT_TYPE_CHOICES, default="tokutei", verbose_name="口座種別"
    )

    note = models.TextField(blank=True, verbose_name="メモ")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-created_at"]
        verbose_name = "取引"
        verbose_name_plural = "取引"

    def __str__(self):
        label = self.company.stock_code if self.company else (self.symbol or "—")
        return f"{self.date} {self.get_transaction_type_display()} {label}"

    @property
    def gross_amount(self):
        if self.transaction_type in ("buy", "sell"):
            q = self.quantity or Decimal("0")
            p = self.price or Decimal("0")
            return q * p
        return self.amount or Decimal("0")

    @property
    def net_amount(self):
        g = self.gross_amount
        if self.transaction_type == "buy":
            return g + self.fees + self.taxes
        if self.transaction_type == "sell":
            return g - self.fees - self.taxes
        if self.transaction_type == "dividend":
            return (self.amount or Decimal("0")) - self.taxes
        if self.transaction_type == "fee":
            return -(self.amount or Decimal("0"))
        if self.transaction_type == "deposit":
            return self.amount or Decimal("0")
        if self.transaction_type == "withdrawal":
            return -(self.amount or Decimal("0"))
        return Decimal("0")

    @property
    def display_name(self):
        if self.company:
            return f"{self.company.stock_code} {self.company.name_ja}"
        return self.symbol or "—"
