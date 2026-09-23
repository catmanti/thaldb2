from django.urls import path

from .views import (
    AdmissionCreateView,
    AdmissionUpdateView,
    ClientCreateView,
    ClientDetailView,
    ClientListView,
    ClientUpdateView,
    TransfusionCreateView,
    TransfusionUpdateView,
    client_admissions_partial_view,
    load_districts_view,
    load_ds_divisions_view,
)

app_name = "clients"

urlpatterns = [
    path("", ClientListView.as_view(), name="client-list"),
    path("create/", ClientCreateView.as_view(), name="client-create"),
    path("<int:pk>/", ClientDetailView.as_view(), name="client-detail"),
    path("<int:pk>/edit/", ClientUpdateView.as_view(), name="client-update"),
    # Admissions & Transfusions routes
    path("<int:client_id>/admissions/create/", AdmissionCreateView.as_view(), name="admission-create"),
    path("<int:client_id>/admissions/partial/", client_admissions_partial_view, name="admissions-partial"),
    path("admissions/<int:pk>/edit/", AdmissionUpdateView.as_view(), name="admission-update"),
    path("admissions/<int:admission_id>/transfusions/create/", TransfusionCreateView.as_view(), name="transfusion-create"),
    path("transfusions/<int:pk>/edit/", TransfusionUpdateView.as_view(), name="transfusion-update"),
    # HTMX location cascading endpoints
    path("load-districts/", load_districts_view, name="load-districts"),
    path("load-ds-divisions/", load_ds_divisions_view, name="load-ds-divisions"),
]
