from django import forms
from taggit.forms import TagField

from .models import WatchList


class WatchListForm(forms.ModelForm):
    tags = TagField(required=False, label="タグ", help_text="カンマ区切りで入力")

    class Meta:
        model = WatchList
        fields = ["name", "description", "is_private", "tags"]
        labels = {
            "name": "リスト名",
            "description": "説明",
            "is_private": "非公開",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class NoteForm(forms.Form):
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))
