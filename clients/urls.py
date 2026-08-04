from django.urls import path

from .views import (
    ClientCreateView,
    ClientDetailView,
    ClientListView,
    ClientUpdateView,
    load_districts_view,
    load_ds_divisions_view,
)

app_name = "clients"

urlpatterns = [
    path("", ClientListView.as_view(), name="client-list"),
    path("create/", ClientCreateView.as_view(), name="client-create"),
    path("<int:pk>/", ClientDetailView.as_view(), name="client-detail"),
    path("<int:pk>/edit/", ClientUpdateView.as_view(), name="client-update"),
    # HTMX location cascading endpoints
    path("load-districts/", load_districts_view, name="load-districts"),
    path("load-ds-divisions/", load_ds_divisions_view, name="load-ds-divisions"),
]
