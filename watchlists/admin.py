from django.contrib import admin

from .models import WatchList, WatchListEntry


class WatchListEntryInline(admin.TabularInline):
    model = WatchListEntry
    extra = 0
    readonly_fields = ["added_at"]


@admin.register(WatchList)
class WatchListAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "is_private", "updated_at"]
    list_filter = ["is_private"]
    search_fields = ["name", "owner__username"]
    inlines = [WatchListEntryInline]
