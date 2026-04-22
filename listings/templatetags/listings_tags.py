from datetime import date as date_type

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def mankei(value):
    """Convert 円 → 百万円 (÷1,000,000), formatted with commas. Returns '—' for None."""
    if value is None:
        return "—"
    try:
        millions = round(int(value) / 1_000_000)
        return f"{millions:,}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def to_pct(value, decimals=1):
    """Convert a ratio (0.08) to a percentage string ('8.0'). Returns '—' for None."""
    if value is None:
        return "—"
    try:
        return f"{float(value) * 100:.{int(decimals)}f}"
    except (TypeError, ValueError):
        return "—"


@register.filter
def fmt_num(value, decimals=0):
    """Format number with commas; wrap negatives in red span. Returns '—' for None."""
    if value is None:
        return "—"
    try:
        v = float(value)
        d = int(decimals)
        formatted = f"{v:,.{d}f}" if d > 0 else f"{int(round(v)):,}"
        if v < 0:
            return mark_safe(f'<span class="text-red-500">{formatted}</span>')
        return formatted
    except (TypeError, ValueError):
        return "—"


@register.simple_tag
def earnings_date(value):
    """
    Render an earnings date with proximity highlighting.
    -30..0 days (just passed): orange
      1..7 days (imminent):    red + まもなく badge
      8..30 days (upcoming):   amber
    Outside ±30 days:          plain
    """
    if not value:
        return mark_safe('<span class="text-gray-900 font-medium">—</span>')
    try:
        today = date_type.today()
        delta = (value - today).days
        label = value.strftime("%Y-%m-%d")
        if delta < -30 or delta > 30:
            return mark_safe(f'<span class="text-gray-900 font-medium">{label}</span>')
        if delta < 0:
            return mark_safe(
                f'<span class="text-orange-500 font-semibold">{label}</span>'
            )
        if delta <= 7:
            return mark_safe(
                f'<span class="text-red-600 font-bold">{label}</span>'
                f'<span class="ml-1.5 text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded">まもなく</span>'
            )
        return mark_safe(f'<span class="text-amber-600 font-semibold">{label}</span>')
    except (TypeError, AttributeError):
        return mark_safe('<span class="text-gray-900 font-medium">—</span>')


@register.filter
def strip_exchange(value):
    """Remove trailing （…） exchange qualifier, e.g. 'プライム（東証）' → 'プライム'."""
    if not value:
        return value
    idx = value.find("（")
    return value[:idx] if idx != -1 else value


@register.simple_tag
def yoy_badge(value):
    """Render a colored ▲/▼ +X.X% badge from a ratio value."""
    if value is None:
        return mark_safe('<span class="text-gray-300 text-xs">—</span>')
    try:
        pct = float(value) * 100
        sign = "+" if pct >= 0 else ""
        color = "text-emerald-600" if pct >= 0 else "text-red-500"
        arrow = "▲" if pct >= 0 else "▼"
        return mark_safe(f'<span class="{color} text-xs">{arrow}&thinsp;{sign}{pct:.1f}%</span>')
    except (TypeError, ValueError):
        return mark_safe('<span class="text-gray-300 text-xs">—</span>')
