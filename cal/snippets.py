from wagtail.snippets.views.snippets import SnippetViewSet, SnippetViewSetGroup

from .models import Holiday


class HolidayViewSet(SnippetViewSet):
    model = Holiday
    menu_label = "祝日"
    icon = "date"
    list_display = ["date", "get_country_display", "name"]
    list_filter = ["country"]
    search_fields = ["name"]
    ordering = ["date", "country"]


class CalendarGroup(SnippetViewSetGroup):
    menu_label = "カレンダー"
    menu_icon = "date"
    menu_order = 300
    items = [HolidayViewSet]
