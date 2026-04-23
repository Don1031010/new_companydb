from django.urls import path

from . import views

app_name = "portfolio"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("transactions/", views.transaction_list, name="transaction_list"),
    path("transactions/new/", views.transaction_create, name="transaction_create"),
    path("transactions/<int:pk>/edit/", views.transaction_edit, name="transaction_edit"),
    path("transactions/<int:pk>/delete/", views.transaction_delete, name="transaction_delete"),
    path("brokers/", views.broker_list, name="broker_list"),
    path("brokers/new/", views.broker_create, name="broker_create"),
    path("brokers/<int:pk>/edit/", views.broker_edit, name="broker_edit"),
    path("brokers/<int:pk>/delete/", views.broker_delete, name="broker_delete"),
]
