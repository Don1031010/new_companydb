from django.contrib.auth.models import User
from django.db import models
from taggit.managers import TaggableManager

from listings.models import Company


class WatchList(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="watchlists")
    name = models.CharField(max_length=100, verbose_name="リスト名")
    description = models.TextField(blank=True, verbose_name="説明")
    is_private = models.BooleanField(default=True, verbose_name="非公開")
    companies = models.ManyToManyField(
        Company, through="WatchListEntry", related_name="watchlists", blank=True
    )
    tags = TaggableManager(blank=True, verbose_name="タグ")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "ウォッチリスト"
        verbose_name_plural = "ウォッチリスト"

    def __str__(self):
        return self.name


class WatchListEntry(models.Model):
    watchlist = models.ForeignKey(WatchList, on_delete=models.CASCADE, related_name="entries")
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="watchlist_entries")
    added_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, verbose_name="メモ")

    class Meta:
        unique_together = [("watchlist", "company")]
        ordering = ["-added_at"]
        verbose_name = "エントリー"
        verbose_name_plural = "エントリー"

    def __str__(self):
        return f"{self.watchlist.name} — {self.company.stock_code}"
