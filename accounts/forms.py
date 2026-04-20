from django import forms
from django.contrib.auth.models import User

from .models import UserProfile


class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=False, label="名")
    last_name = forms.CharField(max_length=150, required=False, label="姓")
    email = forms.EmailField(required=False, label="メールアドレス")

    class Meta:
        model = UserProfile
        fields = ["display_name", "bio", "show_others_events"]
        labels = {
            "display_name": "表示名",
            "bio": "自己紹介",
            "show_others_events": "他のユーザーの公開イベントをカレンダーに表示する",
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email

    def save_user(self, user):
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.save(update_fields=["first_name", "last_name", "email"])
