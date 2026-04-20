from datetime import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import EventForm
from .models import COUNTRY_COLORS, Event, Holiday


SEARCH_TYPES = [("all", "全て"), ("event", "イベント"), ("memo", "メモ")]


@login_required
def calendar_view(request):
    return render(request, "cal/calendar.html", {"search_types": SEARCH_TYPES})


@login_required
def events_json(request):
    """
    Returns events + holidays for the requested date range.
    FullCalendar supplies ?start=YYYY-MM-DD&end=YYYY-MM-DD.
    """
    try:
        start = datetime.fromisoformat(request.GET["start"]).date()
        end = datetime.fromisoformat(request.GET["end"]).date()
    except (KeyError, ValueError):
        return JsonResponse([], safe=False)

    data = []

    date_filter = {"start__date__gte": start, "start__date__lte": end}

    # Own events (all — public and private)
    own_qs = Event.objects.filter(user=request.user, **date_filter)

    # Others' public events (if the user has opted in)
    show_others = getattr(request.user.profile, "show_others_events", True)
    others_qs = (
        Event.objects.filter(is_public=True, **date_filter)
        .exclude(user=request.user)
        .select_related("user")
        if show_others else []
    )

    def serialize(ev, is_own):
        lock = "" if ev.is_public else "🔒 "
        owner_label = f" (@{ev.user.username})" if not is_own else ""
        if ev.is_memo:
            return {
                "id": ev.pk,
                "title": f"{lock}📝 {ev.title}{owner_label}",
                "start": ev.start.date().isoformat(),
                "allDay": True,
                "backgroundColor": ev.color or ("#f5f0e8" if is_own else "#f3f4f6"),
                "borderColor": ev.color or ("#d4a574" if is_own else "#d1d5db"),
                "textColor": "#78350f" if is_own else "#6b7280",
                "classNames": ["memo-event"] + ([] if is_own else ["others-event"]),
                "extendedProps": {
                    "type": "memo", "is_memo": True, "is_own": is_own,
                    "description": ev.description, "owner": ev.user.username,
                    "is_public": ev.is_public,
                },
            }
        else:
            return {
                "id": ev.pk,
                "title": f"{lock}{ev.title}{owner_label}",
                "start": ev.start.isoformat(),
                "end": ev.end.isoformat() if ev.end else None,
                "allDay": ev.all_day,
                "color": ev.color or ("#6366f1" if is_own else "#94a3b8"),
                "classNames": [] if is_own else ["others-event"],
                "extendedProps": {
                    "type": "event", "is_memo": False, "is_own": is_own,
                    "description": ev.description, "owner": ev.user.username,
                    "is_public": ev.is_public,
                },
            }

    for ev in own_qs:
        data.append(serialize(ev, is_own=True))
    for ev in others_qs:
        data.append(serialize(ev, is_own=False))

    # Holidays (all countries)
    for h in Holiday.objects.filter(date__gte=start, date__lte=end):
        color = COUNTRY_COLORS.get(h.country, "#94a3b8")
        if h.country == "JP":
            data.append({
                "id": f"h-{h.pk}",
                "title": h.name,
                "start": h.date.isoformat(),
                "allDay": True,
                "display": "background",
                "color": color,
                "extendedProps": {"type": "holiday", "country": h.country},
            })
        else:
            data.append({
                "id": f"h-{h.pk}",
                "title": f"[{h.country}] {h.name}",
                "start": h.date.isoformat(),
                "allDay": True,
                "backgroundColor": "transparent",
                "borderColor": "transparent",
                "textColor": color,
                "classNames": [f"holiday-text holiday-{h.country.lower()}"],
                "extendedProps": {"type": "holiday", "country": h.country},
            })

    return JsonResponse(data, safe=False)


@login_required
def search_events(request):
    q = request.GET.get("q", "").strip()
    type_filter = request.GET.get("type", "all")  # all | event | memo

    if not q:
        return JsonResponse([], safe=False)

    keyword = Q(title__icontains=q) | Q(description__icontains=q)
    own_qs = Event.objects.filter(user=request.user).filter(keyword)

    show_others = getattr(request.user.profile, "show_others_events", True)
    others_qs = (
        Event.objects.filter(is_public=True).exclude(user=request.user).filter(keyword)
        .select_related("user")
        if show_others else Event.objects.none()
    )

    combined = (own_qs | others_qs).distinct()
    if type_filter == "event":
        combined = combined.filter(is_memo=False)
    elif type_filter == "memo":
        combined = combined.filter(is_memo=True)

    results = []
    for ev in combined.order_by("-start")[:50]:
        is_own = ev.user_id == request.user.pk
        desc = ev.description
        excerpt = ""
        if desc:
            lo = desc.lower()
            idx = lo.find(q.lower())
            if idx >= 0:
                s = max(0, idx - 30)
                chunk = desc[s: idx + len(q) + 40]
                excerpt = ("…" if s > 0 else "") + chunk + ("…" if s + len(chunk) < len(desc) else "")
            else:
                excerpt = desc[:80] + ("…" if len(desc) > 80 else "")

        results.append({
            "id": ev.pk,
            "title": ev.title,
            "date": ev.start.date().isoformat(),
            "is_memo": ev.is_memo,
            "is_own": is_own,
            "owner": ev.user.username,
            "is_public": ev.is_public,
            "excerpt": excerpt,
        })

    return JsonResponse(results, safe=False)


@login_required
def event_create(request):
    initial = {}
    if "start" in request.GET:
        initial["start"] = request.GET["start"]
        initial["end"] = request.GET.get("end", request.GET["start"])

    if request.method == "POST":
        form = EventForm(request.POST)
        if form.is_valid():
            event = form.save(commit=False)
            event.user = request.user
            event.save()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "id": event.pk})
            return redirect("cal:calendar")
    else:
        form = EventForm(initial=initial)

    return render(request, "cal/event_form.html", {"form": form, "action": "作成"})


@login_required
def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk, user=request.user)

    if request.method == "POST":
        # Handle delete
        if request.POST.get("delete"):
            event.delete()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "deleted": True})
            return redirect("cal:calendar")

        form = EventForm(request.POST, instance=event)
        if form.is_valid():
            form.save()
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "id": event.pk})
            return redirect("cal:calendar")
    else:
        form = EventForm(instance=event)

    return render(request, "cal/event_form.html", {"form": form, "event": event, "action": "編集"})
