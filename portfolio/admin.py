from django.contrib import admin

from .models import Broker, Transaction


@admin.register(Broker)
class BrokerAdmin(admin.ModelAdmin):
    list_display = ["name", "owner", "broker_type"]
    list_filter = ["broker_type"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ["date", "owner", "transaction_type", "company", "symbol", "quantity", "price", "fees"]
    list_filter = ["transaction_type", "asset_type", "broker"]
    search_fields = ["company__stock_code", "symbol", "owner__username"]
    date_hierarchy = "date"
