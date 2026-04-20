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


class EventForm(forms.ModelForm):
    color = forms.ChoiceField(
        choices=COLOR_CHOICES,
        required=False,
        label="色",
        widget=forms.Select(attrs={"class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"}),
    )

    class Meta:
        model = Event
        fields = ["title", "start", "end", "all_day", "description", "color"]
        labels = {
            "title": "タイトル",
            "start": "開始",
            "end": "終了",
            "all_day": "終日",
            "description": "メモ",
        }
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm",
                "placeholder": "イベント名",
            }),
            "start": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={
                "type": "datetime-local",
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm",
            }),
            "end": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={
                "type": "datetime-local",
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm",
            }),
            "all_day": forms.CheckboxInput(attrs={"class": "rounded border-gray-300 text-indigo-600"}),
            "description": forms.Textarea(attrs={
                "class": "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm",
                "rows": 3,
            }),
        }
