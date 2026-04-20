from django.contrib.auth.models import User
from django.db import models


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    show_others_events = models.BooleanField(default=True, verbose_name="他のユーザーのイベントを表示")

    def __str__(self):
        return self.display_name or self.user.username

    def get_name(self):
        return self.display_name or self.user.get_full_name() or self.user.username
