from django import forms

from .models import Broker, Transaction, TRANSACTION_TYPE_CHOICES


class BrokerForm(forms.ModelForm):
    class Meta:
        model = Broker
        fields = ["name", "broker_type", "notes"]
        labels = {"name": "ブローカー名", "broker_type": "種別", "notes": "備考"}
        widgets = {"notes": forms.Textarea(attrs={"rows": 2})}


class TransactionForm(forms.ModelForm):
    stock_code = forms.CharField(
        max_length=20, required=False, label="銘柄コード",
        help_text="上場銘柄の場合は証券コードを入力",
    )

    class Meta:
        model = Transaction
        fields = [
            "broker", "date", "transaction_type", "account_type",
            "stock_code", "quantity", "price",
            "fees", "taxes", "amount", "note",
        ]
        labels = {
            "broker":           "ブローカー",
            "date":             "取引日",
            "transaction_type": "取引種別",
            "account_type":     "口座種別",
            "quantity":         "数量（株）",
            "price":            "単価（円）",
            "fees":             "手数料（円）",
            "taxes":            "税金（円）",
            "amount":           "金額（円）",
            "note":             "メモ",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["broker"].queryset = Broker.objects.filter(owner=user)
        self.fields["broker"].required = False
        # Pre-fill stock_code when editing
        if self.instance.pk and self.instance.company:
            self.fields["stock_code"].initial = self.instance.company.stock_code

    def clean(self):
        cleaned = super().clean()
        txn_type = cleaned.get("transaction_type")
        stock_code = (cleaned.get("stock_code") or "").strip().upper()

        if txn_type in ("buy", "sell", "dividend") and stock_code:
            from listings.models import Company
            try:
                cleaned["_company"] = Company.objects.get(stock_code=stock_code)
            except Company.DoesNotExist:
                self.add_error("stock_code", f"銘柄コード「{stock_code}」が見つかりません。")

        if txn_type in ("buy", "sell"):
            if not cleaned.get("quantity"):
                self.add_error("quantity", "必須項目です。")
            if not cleaned.get("price"):
                self.add_error("price", "必須項目です。")

        if txn_type in ("dividend", "fee", "deposit", "withdrawal"):
            if not cleaned.get("amount"):
                self.add_error("amount", "必須項目です。")

        return cleaned
