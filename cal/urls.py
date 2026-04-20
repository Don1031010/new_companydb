from django.urls import path

from . import views

app_name = "cal"

urlpatterns = [
    path("", views.calendar_view, name="calendar"),
    path("api/events/", views.events_json, name="events_json"),
    path("events/new/", views.event_create, name="event_create"),
    path("events/<int:pk>/", views.event_edit, name="event_edit"),
    path("api/search/", views.search_events, name="search_events"),
]
