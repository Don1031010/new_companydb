from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ProfileForm


@login_required
def profile(request):
    return render(request, "accounts/profile.html")


@login_required
def profile_edit(request):
    user = request.user
    profile = user.profile

    if request.method == "POST":
        form = ProfileForm(request.POST, instance=profile, user=user)
        if form.is_valid():
            form.save()
            form.save_user(user)
            return redirect("accounts:profile")
    else:
        form = ProfileForm(instance=profile, user=user)

    return render(request, "accounts/profile_edit.html", {"form": form})
