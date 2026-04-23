from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from listings.models import Company

from .forms import NoteForm, WatchListForm
from .models import WatchList, WatchListEntry


@login_required
def watchlist_index(request):
    qs = request.user.watchlists.prefetch_related("tags")
    q = request.GET.get("q", "").strip()
    tag = request.GET.get("tag", "").strip()

    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    if tag:
        qs = qs.filter(tags__name=tag)

    return render(request, "watchlists/watchlist_index.html", {
        "watchlists": qs.distinct(),
        "q": q,
        "tag": tag,
    })


@login_required
def watchlist_create(request):
    if request.method == "POST":
        form = WatchListForm(request.POST)
        if form.is_valid():
            wl = form.save(commit=False)
            wl.owner = request.user
            wl.save()
            form.save_m2m()
            return redirect("watchlists:detail", pk=wl.pk)
    else:
        form = WatchListForm()
    return render(request, "watchlists/watchlist_form.html", {"form": form, "action": "create"})


def watchlist_detail(request, pk):
    wl = get_object_or_404(WatchList, pk=pk)
    if wl.is_private and (not request.user.is_authenticated or wl.owner != request.user):
        raise Http404

    entries = wl.entries.select_related("company").prefetch_related("company__listings__exchange")
    q = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "")

    if q:
        entries = entries.filter(
            Q(company__stock_code__icontains=q) | Q(company__name_ja__icontains=q)
        )
    if sort == "market_cap_desc":
        entries = entries.order_by("-company__market_cap")
    elif sort == "market_cap_asc":
        entries = entries.order_by("company__market_cap")
    elif sort == "code":
        entries = entries.order_by("company__stock_code")

    return render(request, "watchlists/watchlist_detail.html", {
        "wl": wl,
        "entries": entries,
        "is_owner": request.user.is_authenticated and request.user == wl.owner,
        "q": q,
        "sort": sort,
    })


@login_required
def watchlist_edit(request, pk):
    wl = get_object_or_404(WatchList, pk=pk, owner=request.user)
    if request.method == "POST":
        form = WatchListForm(request.POST, instance=wl)
        if form.is_valid():
            form.save()
            return redirect("watchlists:detail", pk=wl.pk)
    else:
        form = WatchListForm(instance=wl)
    return render(request, "watchlists/watchlist_form.html", {"form": form, "wl": wl, "action": "edit"})


@login_required
def watchlist_delete(request, pk):
    wl = get_object_or_404(WatchList, pk=pk, owner=request.user)
    if request.method == "POST":
        wl.delete()
        return redirect("watchlists:index")
    return render(request, "watchlists/watchlist_confirm_delete.html", {"wl": wl})


@login_required
def add_company(request, pk):
    if request.method != "POST":
        return redirect("watchlists:index")
    wl = get_object_or_404(WatchList, pk=pk, owner=request.user)
    stock_code = request.POST.get("stock_code", "").strip()
    company = get_object_or_404(Company, stock_code=stock_code)
    WatchListEntry.objects.get_or_create(watchlist=wl, company=company)
    next_url = request.POST.get("next") or "/"
    return redirect(next_url)


@login_required
def remove_company(request, pk, stock_code):
    if request.method != "POST":
        return redirect("watchlists:index")
    wl = get_object_or_404(WatchList, pk=pk, owner=request.user)
    WatchListEntry.objects.filter(watchlist=wl, company__stock_code=stock_code).delete()
    next_url = request.POST.get("next") or "/"
    return redirect(next_url)


@login_required
def edit_note(request, pk, stock_code):
    if request.method != "POST":
        return redirect("watchlists:detail", pk=pk)
    entry = get_object_or_404(
        WatchListEntry,
        watchlist__pk=pk,
        watchlist__owner=request.user,
        company__stock_code=stock_code,
    )
    form = NoteForm(request.POST)
    if form.is_valid():
        entry.note = form.cleaned_data["note"]
        entry.save(update_fields=["note"])
    return redirect("watchlists:detail", pk=pk)
