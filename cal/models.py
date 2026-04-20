from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _
from wagtail.admin.panels import FieldPanel, FieldRowPanel


COUNTRY_CHOICES = [
    ("JP", "🇯🇵 日本"),
    ("CN", "🇨🇳 中国"),
    ("US", "🇺🇸 米国"),
]

COUNTRY_COLORS = {
    "JP": "#ef4444",
    "CN": "#f59e0b",
    "US": "#3b82f6",
}


class Holiday(models.Model):
    date = models.DateField(verbose_name=_("日付"))
    name = models.CharField(max_length=200, verbose_name=_("祝日名"))
    country = models.CharField(
        max_length=2,
        choices=COUNTRY_CHOICES,
        default="JP",
        verbose_name=_("国"),
        db_index=True,
    )

    panels = [
        FieldRowPanel([
            FieldPanel("date"),
            FieldPanel("country"),
        ]),
        FieldPanel("name"),
    ]

    class Meta:
        verbose_name = _("祝日")
        verbose_name_plural = _("祝日")
        unique_together = [("date", "country")]
        ordering = ["date", "country"]

    def __str__(self):
        return f"{self.date} [{self.country}] {self.name}"


class Event(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="cal_events",
        verbose_name=_("ユーザー"),
    )
    title = models.CharField(max_length=200, verbose_name=_("タイトル"))
    start = models.DateTimeField(verbose_name=_("開始"))
    end = models.DateTimeField(null=True, blank=True, verbose_name=_("終了"))
    all_day = models.BooleanField(default=False, verbose_name=_("終日"))
    description = models.TextField(blank=True, verbose_name=_("メモ"))
    color = models.CharField(max_length=20, blank=True, verbose_name=_("色"))
    is_memo = models.BooleanField(default=False, verbose_name=_("メモ/日記"))
    is_public = models.BooleanField(default=True, verbose_name=_("公開"))

    class Meta:
        verbose_name = _("イベント")
        verbose_name_plural = _("イベント")
        ordering = ["start"]

    def __str__(self):
        return f"{self.title} ({self.start:%Y-%m-%d})"
