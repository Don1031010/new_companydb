from django.urls import path

from . import views

app_name = "watchlists"

urlpatterns = [
    path("", views.watchlist_index, name="index"),
    path("new/", views.watchlist_create, name="create"),
    path("<int:pk>/", views.watchlist_detail, name="detail"),
    path("<int:pk>/edit/", views.watchlist_edit, name="edit"),
    path("<int:pk>/delete/", views.watchlist_delete, name="delete"),
    path("<int:pk>/add/", views.add_company, name="add_company"),
    path("<int:pk>/remove/<str:stock_code>/", views.remove_company, name="remove_company"),
    path("<int:pk>/note/<str:stock_code>/", views.edit_note, name="edit_note"),
]
