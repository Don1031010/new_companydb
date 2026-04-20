from django import template

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
