"""
models.py — Japanese Listed Company models

Architecture:
  StockExchange  ←──(through: Listing)──→  Company
  
  - StockExchange: TSE, NSE, SSE, etc.
  - Company:       Core company data (names, codes, sector, etc.)
  - Listing:       The M2M through model — carries segment, dates, status per listing
  - IndustryCode:  33-industry classification (reusable lookup table)
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, InlinePanel, MultiFieldPanel, FieldRowPanel
from modelcluster.models import ClusterableModel
from modelcluster.fields import ParentalKey, ParentalManyToManyField


# ─────────────────────────────────────────────────────────────────────────────
# Lookup: 33-industry classification (東証33業種)
# ─────────────────────────────────────────────────────────────────────────────

INDUSTRY_33_CHOICES = [
    ("0050", "水産・農林業"),
    ("1050", "鉱業"),
    ("2050", "建設業"),
    ("3050", "食料品"),
    ("3100", "繊維製品"),
    ("3150", "パルプ・紙"),
    ("3200", "化学"),
    ("3250", "医薬品"),
    ("3300", "石油・石炭製品"),
    ("3350", "ゴム製品"),
    ("3400", "ガラス・土石製品"),
    ("3450", "鉄鋼"),
    ("3500", "非鉄金属"),
    ("3550", "金属製品"),
    ("3600", "機械"),
    ("3650", "電気機器"),
    ("3700", "輸送用機器"),
    ("3750", "精密機器"),
    ("3800", "その他製品"),
    ("4050", "電気・ガス業"),
    ("5050", "陸運業"),
    ("5100", "海運業"),
    ("5150", "空運業"),
    ("5200", "倉庫・運輸関連業"),
    ("5250", "情報・通信業"),
    ("6050", "卸売業"),
    ("6100", "小売業"),
    ("7050", "銀行業"),
    ("7100", "証券・商品先物取引業"),
    ("7150", "保険業"),
    ("7200", "その他金融業"),
    ("8050", "不動産業"),
    ("9050", "サービス業"),
]

INDUSTRY_17_CHOICES = [
    ("1",  "食品"),
    ("2",  "エネルギー資源"),
    ("3",  "建設・資材"),
    ("4",  "素材・化学"),
    ("5",  "医薬品・バイオ"),
    ("6",  "自動車・輸送機"),
    ("7",  "鉄鋼・非鉄"),
    ("8",  "機械"),
    ("9",  "電機・精機"),
    ("10", "ＩＴ・サービス・その他"),
    ("11", "電気・ガス・水道"),
    ("12", "運輸・物流"),
    ("13", "商社・卸売"),
    ("14", "小売"),
    ("15", "銀行"),
    ("16", "金融（除く銀行）"),
    ("17", "不動産"),
]

SCALE_CHOICES = [
    ("large",  "大型"),
    ("mid",    "中型"),
    ("small",  "小型"),
    ("other",  "その他"),
]

FISCAL_MONTH_CHOICES = [(str(i), f"{i}月") for i in range(1, 13)]

COMPANY_STATUS_CHOICES = [
    ("active",   "上場中"),
    ("delisted", "上場廃止"),
    ("watchlist","整理・監理銘柄"),
    ("suspended","売買停止"),
]


# ─────────────────────────────────────────────────────────────────────────────
# StockExchange
# ─────────────────────────────────────────────────────────────────────────────

class StockExchange(models.Model):
    """
    Represents a Japanese stock exchange (TSE, NSE, SSE, FSE, etc.)
    """
    # Identifiers
    code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name=_("取引所コード"),
        help_text=_("例: TSE, NSE, SSE, FSE"),
    )
    name_ja = models.CharField(max_length=100, verbose_name=_("取引所名（日本語）"))
    name_en = models.CharField(max_length=100, verbose_name=_("取引所名（英語）"), blank=True)
    short_name = models.CharField(
        max_length=20,
        verbose_name=_("略称"),
        blank=True,
        help_text=_("例: 東証, 名証, 札証"),
    )
    website = models.URLField(blank=True, verbose_name=_("ウェブサイト"))

    panels = [
        FieldRowPanel([
            FieldPanel("code"),
            FieldPanel("short_name"),
        ]),
        FieldPanel("name_ja"),
        FieldPanel("name_en"),
        FieldPanel("website"),
    ]

    class Meta:
        verbose_name = _("証券取引所")
        verbose_name_plural = _("証券取引所")
        ordering = ["code"]

    def __str__(self):
        return f"{self.short_name or self.name_ja} ({self.code})"


# ─────────────────────────────────────────────────────────────────────────────
# Market Segment choices (per exchange)
# ─────────────────────────────────────────────────────────────────────────────

MARKET_SEGMENT_CHOICES = [
    # TSE
    ("tse_prime",    "プライム（東証）"),
    ("tse_standard", "スタンダード（東証）"),
    ("tse_growth",   "グロース（東証）"),
    ("tse_pro",      "TOKYO PRO Market"),
    ("tse_etf",      "ETF（東証）"),
    ("tse_reit",     "REIT（東証）"),
    ("tse_infra",    "インフラファンド（東証）"),
    # NSE (名証)
    ("nse_premier",  "プレミア（名証）"),
    ("nse_main",     "メイン（名証）"),
    ("nse_next",     "ネクスト（名証）"),
    # SSE (札証)
    ("sse_main",     "本則市場（札証）"),
    ("sse_ambitious","アンビシャス（札証）"),
    ("sse_frontier", "Sapporo PRO Frontier"),
    # FSE (福証)
    ("fse_main",      "本則市場（福証）"),
    ("fse_q_board",   "Q-Board（福証）"),
    ("fse_pro_market","Fukuoka PRO Market（福証）"),
]

LISTING_STATUS_CHOICES = [
    ("active",   "上場中"),
    ("delisted", "上場廃止"),
    ("transferred", "市場変更"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Company
# ─────────────────────────────────────────────────────────────────────────────

class Company(ClusterableModel):
    """
    A Japanese listed (or formerly listed) company.

    Many-to-many relationship with StockExchange is managed via the
    Listing through model, which stores segment, dates, and status
    per exchange per company.
    """

    # ── Identifiers ──────────────────────────────────────────────────────────
    stock_code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name=_("証券コード"),
        # help_text=_("4桁の証券コード（例: 7203）"),
        db_index=True,
    )
    edinet_code = models.CharField(
        max_length=8,
        blank=True,
        verbose_name=_("EDINETコード"),
        help_text=_("例: E02167"),
        db_index=True,
    )

    # ── Names ─────────────────────────────────────────────────────────────────
    name_ja = models.CharField(
        max_length=200,
        verbose_name=_("会社名（日本語）"),
        db_index=True,
    )
    name_kana = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("会社名（かな）"),
        # help_text=_("全角カタカナ"),
        db_index=True,
    )
    name_en = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("会社名（英語）"),
        db_index=True,
    )
    short_name_ja = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("略称（日本語）"),
        help_text=_("例: トヨタ"),
    )
    established_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("設立年月日"),
    )
    representative_name = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("代表者氏名"),
        help_text=_("例: 井上 誠"),
    )
    representative_title = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("代表者役職"),
        help_text=_("例: 代表取締役社長"),
    )
    
    # ── Exchange relationship (M2M via Listing) ───────────────────────────────
    # Direct access: company.listings.all() → Listing queryset
    # Convenience: company.exchanges.all() → StockExchange queryset
    exchanges = models.ManyToManyField(
        StockExchange,
        through="Listing",
        related_name="companies",
        verbose_name=_("上場取引所"),
        blank=True,
    )

    # ── Classification ────────────────────────────────────────────────────────
    industry_33 = models.CharField(
        max_length=10,
        choices=INDUSTRY_33_CHOICES,
        blank=True,
        verbose_name=_("業種（33業種）"),
    )
    industry_17 = models.CharField(
        max_length=10,
        choices=INDUSTRY_17_CHOICES,
        blank=True,
        verbose_name=_("業種（17業種）"),
    )
    scale_category = models.CharField(
        max_length=10,
        choices=SCALE_CHOICES,
        blank=True,
        verbose_name=_("規模区分"),
    )
    is_margin_trading = models.BooleanField(
        default=False,
        verbose_name=_("信用銘柄"),
        help_text=_("一般信用"),
    )
    is_securities_lending = models.BooleanField(
        default=False,
        verbose_name=_("貸借銘柄"),
        help_text=_("制度信用"),
    )
    
    # ── Financials / Calendar ─────────────────────────────────────────────────
    fiscal_year_end_month = models.CharField(
        max_length=2,
        choices=FISCAL_MONTH_CHOICES,
        blank=True,
        verbose_name=_("決算期（月）"),
    )
    fiscal_year_end_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name=_("決算期（日）"),
        help_text=_("決算期末の日付。月末の場合は空欄。"),
    )
    earnings_date_annual = models.DateField(
        null=True, blank=True,
        verbose_name=_("決算発表（予定）"),
    )
    earnings_date_q1 = models.DateField(
        null=True, blank=True,
        verbose_name=_("第一四半期（予定）"),
    )
    earnings_date_q2 = models.DateField(
        null=True, blank=True,
        verbose_name=_("第二四半期（予定）"),
    )
    earnings_date_q3 = models.DateField(
        null=True, blank=True,
        verbose_name=_("第三四半期（予定）"),
    )
    shares_outstanding = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("発行済株式数"),
    )
    treasury_shares = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("自己株式数"),
        help_text=_("EDINETより取得。市場流通株数 = 発行済株式数 − 自己株式数"),
    )
    share_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("株価（円）"),
    )
    share_price_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("株価時刻"),
    )
    yearly_high = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("年初来高値（円）"),
    )
    yearly_high_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("年初来高値日付"),
    )
    yearly_low = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("年初来安値（円）"),
    )
    yearly_low_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("年初来安値日付"),
    )
    market_cap = models.DecimalField(
        max_digits=20,
        decimal_places=0,
        null=True,
        blank=True,
        verbose_name=_("時価総額（百万円）"),
    )
    unit_shares = models.IntegerField(
        default=100,
        verbose_name=_("売買単位"),
        # help_text=_("通常100株"),
    )

    # ── Contact / Location ────────────────────────────────────────────────────
    website = models.URLField(blank=True, verbose_name=_("ウェブサイト"))
    address_postal_code = models.CharField(
        max_length=10,
        blank=True,
        verbose_name=_("郵便番号"),
    )
    address_ja = models.CharField(
        max_length=300,
        blank=True,
        verbose_name=_("所在地（日本語）"),
    )
    address_en = models.CharField(
        max_length=300,
        blank=True,
        verbose_name=_("所在地（英語）"),
    )
    phone = models.CharField(max_length=20, blank=True, verbose_name=_("電話番号"))

    # ── Status & flags ────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=COMPANY_STATUS_CHOICES,
        default="active",
        verbose_name=_("ステータス"),
        db_index=True,
    )
    is_foreign = models.BooleanField(
        default=False,
        verbose_name=_("外国株"),
        help_text=_("外国企業の上場"),
    )
    # is_etf = models.BooleanField(
    #     default=False,
    #     verbose_name=_("ETF / ETN"),
    # )
    # is_reit = models.BooleanField(
    #     default=False,
    #     verbose_name=_("REIT / インフラファンド"),
    # )
    is_non_jpx = models.BooleanField(
        default=True,
        verbose_name=_("東証非上場"),
        help_text=_("東証非上場"),
    )

    # ── Narrative ─────────────────────────────────────────────────────────────
    description_ja = models.TextField(blank=True, verbose_name=_("会社概要（日本語）"))
    description_en = models.TextField(blank=True, verbose_name=_("会社概要（英語）"))

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    detail_scraped_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("詳細取得日時"),
        help_text=_("Phase 2で詳細情報を取得した日時"),
    )
    disclosures_scraped_at = models.DateTimeField(
        null=True, blank=True,
        verbose_name=_("適時開示取得日時"),
        help_text=_("適時開示情報を最後に取得した日時"),
    )

    # ── Wagtail admin panels ──────────────────────────────────────────────────
    panels = [
        # MultiFieldPanel([
        #     FieldRowPanel([
        #         FieldPanel("stock_code"),
        #         FieldPanel("status"),
        #     ]),
        # ], heading=_("基本情報")),

        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("stock_code"),
                FieldPanel("edinet_code"),
                FieldPanel("status"),
            ]),
            FieldPanel("name_ja"),
            FieldPanel("name_kana"),
            FieldPanel("name_en"),
            FieldPanel("short_name_ja"),
            FieldPanel("established_date"),
            FieldPanel("representative_name"),
            FieldPanel("representative_title"),
        ], heading=_("基本情報")),

        # Listings (exchanges + segments) managed via inline
        MultiFieldPanel([
            InlinePanel("listings", label=_("上場情報"), min_num=0),
        ], heading=_("上場取引所")),

        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("industry_33"),
                FieldPanel("industry_17"),
            ]),
            FieldRowPanel([
                FieldPanel("scale_category"),
                FieldPanel("fiscal_year_end_month"),
                FieldPanel("fiscal_year_end_day"),
            ]),
        ], heading=_("業種・規模")),

        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("shares_outstanding"),
                FieldPanel("treasury_shares"),
                FieldPanel("unit_shares"),
            ]),
            FieldRowPanel([
                FieldPanel("share_price"),
                FieldPanel("market_cap"),
            ]),
            FieldRowPanel([
                FieldPanel("yearly_high"),
                FieldPanel("yearly_high_date"),
            ]),
            FieldRowPanel([
                FieldPanel("yearly_low"),
                FieldPanel("yearly_low_date"),
            ]),
        ], heading=_("株式情報")),

        MultiFieldPanel([
            InlinePanel("share_records", label=_("大株主"), min_num=0),
        ], heading=_("大株主情報")),

        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("earnings_date_annual"),
                FieldPanel("earnings_date_q1"),
            ]),
            FieldRowPanel([
                FieldPanel("earnings_date_q2"),
                FieldPanel("earnings_date_q3"),
            ]),
        ], heading=_("決算発表日（予定）")),

        MultiFieldPanel([
            FieldPanel("website"),
            FieldRowPanel([
                FieldPanel("address_postal_code"),
                FieldPanel("phone"),
            ]),
            FieldPanel("address_ja"),
            FieldPanel("address_en"),
        ], heading=_("連絡先・所在地")),

        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("is_foreign"),
                FieldPanel("is_non_jpx"),
                FieldPanel("is_margin_trading"),
                FieldPanel("is_securities_lending"),
            ]),
        ], heading=_("区分フラグ")),

        MultiFieldPanel([
            FieldPanel("description_ja"),
            FieldPanel("description_en"),
        ], heading=_("会社概要")),
    ]

    class Meta:
        verbose_name = _("上場会社")
        verbose_name_plural = _("上場会社")
        ordering = ["stock_code"]
        indexes = [
            models.Index(fields=["stock_code"]),
            models.Index(fields=["name_ja"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.stock_code}　{self.name_ja}"

    def save(self, *args, **kwargs):
        if self.shares_outstanding and self.share_price:
            self.market_cap = self.shares_outstanding * self.share_price / 1_000_000
        super().save(*args, **kwargs)

    @property
    def treasury_shares_pct(self):
        if self.shares_outstanding and self.treasury_shares:
            return round(self.treasury_shares / self.shares_outstanding * 100, 1)
        return None

    @property
    def primary_exchange(self):
        """Returns the first active listing's exchange (TSE first if dual-listed)."""
        listing = (
            self.listings.filter(status="active")
            .select_related("exchange")
            .order_by("exchange__code")
            .first()
        )
        return listing.exchange if listing else None

    @property
    def active_listings(self):
        return self.listings.filter(status="active").select_related("exchange")

    @property
    def display_name(self):
        return f"{self.name_ja}（{self.stock_code}）"


# ─────────────────────────────────────────────────────────────────────────────
# Listing  — the M2M through model
# ─────────────────────────────────────────────────────────────────────────────

class Listing(models.Model):
    """
    Represents one company's listing on one exchange.
    A dual-listed company (e.g. on TSE + NSE) will have two Listing rows.
    
    This through model carries the data that belongs to the *relationship*,
    not to either parent alone:
      - Which market segment within the exchange
      - When it was listed / delisted
      - Current listing status
    """
    company = ParentalKey(
        "Company",
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name=_("会社"),
    )
    exchange = models.ForeignKey(
        StockExchange,
        on_delete=models.PROTECT,
        related_name="listings",
        verbose_name=_("取引所"),
    )

    # ── Segment ────────────────────────────────────────────────────────────────
    market_segment = models.CharField(
        max_length=30,
        choices=MARKET_SEGMENT_CHOICES,
        blank=True,
        verbose_name=_("市場区分"),
    )

    # ── Dates ─────────────────────────────────────────────────────────────────
    listing_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("上場日"),
    )
    delisting_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("上場廃止日"),
    )

    # ── Status ────────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=LISTING_STATUS_CHOICES,
        default="active",
        verbose_name=_("上場ステータス"),
        db_index=True,
    )

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(
        blank=True,
        verbose_name=_("備考"),
        help_text=_("市場区分変更の経緯など"),
    )

    # Wagtail InlinePanel panels (rendered inside Company's admin)
    panels = [
        FieldRowPanel([
            FieldPanel("exchange"),
            FieldPanel("market_segment"),
        ]),
        FieldRowPanel([
            FieldPanel("listing_date"),
            FieldPanel("delisting_date"),
        ]),
        FieldPanel("status"),
        FieldPanel("notes"),
    ]

    class Meta:
        verbose_name = _("上場情報")
        verbose_name_plural = _("上場情報")
        unique_together = [("company", "exchange")]   # one row per company+exchange
        ordering = ["exchange__code"]

    def __str__(self):
        return (
            f"{self.company.stock_code} @ {self.exchange.code}"
            f" [{self.get_market_segment_display()}]"
        )


# ─────────────────────────────────────────────────────────────────────────────
# EDINETDocument — cached document index
# ─────────────────────────────────────────────────────────────────────────────

class EDINETDocument(models.Model):
    """
    Cached entry from the EDINET document list API.
    Populated by fetch_shareholders Phase 1; avoids re-scanning past dates.
    """
    doc_id = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="書類管理番号",
        db_index=True,
    )
    edinet_code = models.CharField(
        max_length=8,
        verbose_name="EDINETコード",
        db_index=True,
    )
    ordinance_code = models.CharField(max_length=10, verbose_name="府令コード")
    form_code = models.CharField(max_length=10, verbose_name="様式コード")
    period_end = models.DateField(null=True, blank=True, verbose_name="期間終了日")
    submit_date = models.DateField(verbose_name="提出日", db_index=True)
    description = models.CharField(max_length=300, blank=True, verbose_name="書類概要")
    withdrawn = models.BooleanField(default=False, verbose_name="取下げ")

    class Meta:
        verbose_name = "EDINET書類"
        verbose_name_plural = "EDINET書類"
        ordering = ["-submit_date"]
        indexes = [
            models.Index(fields=["edinet_code", "-submit_date"]),
        ]

    def __str__(self):
        return f"{self.doc_id} ({self.edinet_code} {self.submit_date})"


# ─────────────────────────────────────────────────────────────────────────────
# Institution, Shareholder & ShareRecord
# ─────────────────────────────────────────────────────────────────────────────

class Institution(models.Model):
    """
    A parent financial institution that owns or manages multiple shareholder
    accounts (e.g. 日本マスタートラスト信託銀行 owns several 信託口 accounts).
    Linking shareholders to an institution allows aggregating their combined
    holdings across companies.
    """
    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name=_("機関名"),
        db_index=True,
    )
    name_en = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("機関名（英語）"),
    )
    name_zh = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("機関名（中国語）"),
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("name_en"),
        FieldPanel("name_zh"),
    ]

    class Meta:
        verbose_name = _("親機関")
        verbose_name_plural = _("親機関")
        ordering = ["name"]

    def __str__(self):
        return self.name


class Shareholder(models.Model):
    """
    A named shareholder entity (institution, individual, or trust account).
    Identified by exact name — different trust accounts of the same bank
    (e.g. 日本マスター信託口 vs 日本マスター信託口(議決権受託行使型)) are
    stored as separate records.

    Optionally linked to an Institution to enable grouped queries.
    """
    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name=_("株主名"),
        db_index=True,
    )
    address = models.CharField(
        max_length=300,
        blank=True,
        verbose_name=_("住所"),
    )
    institution = models.ForeignKey(
        Institution,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="shareholders",
        verbose_name=_("親機関"),
    )

    panels = [
        FieldPanel("name"),
        FieldPanel("address"),
        FieldPanel("institution"),
    ]

    class Meta:
        verbose_name = _("株主")
        verbose_name_plural = _("株主")
        ordering = ["name"]

    def __str__(self):
        return self.name


class DisclosureRecord(models.Model):
    """
    One 適時開示情報 entry for a company, scraped from the JPX detail page.

    Both ・[決算情報] (id="1101_N") and ・[決定事実 / 発生事実] (id="1102_N") rows
    are scraped, with 1101 rows processed first. When the same PDF URL appears in
    both tables (e.g. 決算短信), the 1101 version wins because it carries richer
    data (HTML links). 1102-only entries (M&A, buybacks, etc.) are also stored.

    pdf_url is the natural key for deduplication; rows without a PDF link are skipped.
    """
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="disclosures",
        verbose_name=_("会社"),
    )
    disclosed_date = models.DateField(verbose_name=_("開示日"), db_index=True)
    title = models.CharField(max_length=500, verbose_name=_("表題"))
    pdf_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name=_("PDF"),
    )
    xbrl_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name=_("XBRL"),
    )
    html_summary_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name=_("HTML（サマリー）"),
    )
    html_attachment_url = models.URLField(
        max_length=500,
        blank=True,
        verbose_name=_("HTML（添付）"),
    )
    pdf_filename = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("PDFファイル名"),
        help_text="e.g. 140120260406599058.pdf — stable across TDnet and JPX",
    )
    scraped_at = models.DateTimeField(auto_now=True, verbose_name=_("取得日時"))

    panels = [
        MultiFieldPanel([
            FieldRowPanel([
                FieldPanel("company", read_only=True),
                FieldPanel("disclosed_date", read_only=True),
            ]),
            FieldPanel("title", read_only=True),
        ], heading=_("基本情報")),
        MultiFieldPanel([
            FieldPanel("pdf_url", read_only=True),
            FieldPanel("xbrl_url", read_only=True),
            FieldPanel("html_summary_url", read_only=True),
            FieldPanel("html_attachment_url", read_only=True),
        ], heading=_("資料リンク")),
    ]

    class Meta:
        verbose_name = _("適時開示")
        verbose_name_plural = _("適時開示")
        ordering = ["company__stock_code", "-disclosed_date"]
        indexes = [
            models.Index(fields=["company", "-disclosed_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "pdf_filename"],
                condition=models.Q(pdf_filename__gt=""),
                name="unique_disclosure_company_filename",
            ),
        ]

    def __str__(self):
        return f"{self.company.stock_code} {self.disclosed_date} {self.title[:60]}"


class ShareRecord(models.Model):
    """
    One major shareholder's holding in one company (current snapshot).
    Replacing all records for a company on each scrape gives the latest
    disclosed top-10 shareholders.
    """
    company = ParentalKey(
        Company,
        on_delete=models.CASCADE,
        related_name="share_records",
        verbose_name=_("会社"),
    )
    shareholder = models.ForeignKey(
        Shareholder,
        on_delete=models.PROTECT,
        related_name="share_records",
        verbose_name=_("株主"),
    )
    rank = models.PositiveSmallIntegerField(
        verbose_name=_("順位"),
        help_text=_("大株主順位（1〜10）"),
    )
    shares = models.BigIntegerField(
        null=True,
        blank=True,
        verbose_name=_("保有株数（株）"),
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name=_("持株比率（%）"),
    )
    as_of_date = models.DateField(
        null=True,
        blank=True,
        verbose_name=_("基準日"),
        help_text=_("株主名簿の基準日（通常は決算期末）"),
    )

    panels = [
        FieldRowPanel([
            FieldPanel("rank"),
            FieldPanel("shareholder"),
        ]),
        FieldRowPanel([
            FieldPanel("shares"),
            FieldPanel("percentage"),
            FieldPanel("as_of_date"),
        ]),
    ]

    class Meta:
        verbose_name = _("大株主情報")
        verbose_name_plural = _("大株主情報")
        unique_together = [("company", "rank")]
        ordering = ["company", "rank"]

    def __str__(self):
        return f"{self.company.stock_code} #{self.rank} {self.shareholder.name} ({self.percentage}%)"
