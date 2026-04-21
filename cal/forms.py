from django import forms

from .models import Event

COLOR_CHOICES = [
    ("#6366f1", "インディゴ"),
    ("#10b981", "グリーン"),
    ("#f59e0b", "アンバー"),
    ("#ef4444", "レッド"),
    ("#8b5cf6", "パープル"),
    ("#ec4899", "ピンク"),
    ("#06b6d4", "シアン"),
    ("#64748b", "グレー"),
]

_cb_cls = "rounded border-gray-300"
_field_cls = "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"


class EventForm(forms.ModelForm):
    color = forms.ChoiceField(
        choices=COLOR_CHOICES,
        required=False,
        label="色",
        widget=forms.Select(attrs={"class": _field_cls}),
    )
    # Explicit BooleanFields so required=False is enforced regardless of model blank setting.
    all_day = forms.BooleanField(
        required=False,
        label="終日",
        widget=forms.CheckboxInput(attrs={"class": _cb_cls + " text-indigo-600"}),
    )
    is_memo = forms.BooleanField(
        required=False,
        label="メモ/日記",
        widget=forms.CheckboxInput(attrs={"class": _cb_cls + " text-amber-600"}),
    )
    is_public = forms.BooleanField(
        required=False,
        label="公開",
        widget=forms.CheckboxInput(attrs={"class": _cb_cls + " text-indigo-600"}),
    )

    class Meta:
        model = Event
        fields = ["title", "start", "end", "all_day", "is_memo", "is_public", "description", "color"]
        labels = {
            "title": "タイトル",
            "start": "開始",
            "end": "終了",
            "description": "メモ",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "class": _field_cls,
                "placeholder": "イベント名",
            }),
            "start": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={
                "type": "datetime-local",
                "class": _field_cls,
            }),
            "end": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={
                "type": "datetime-local",
                "class": _field_cls,
            }),
            "description": forms.Textarea(attrs={
                "class": _field_cls,
                "rows": 3,
            }),
        }
