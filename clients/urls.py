from django.urls import path

from .views import (
    AdmissionCreateView,
    AdmissionUpdateView,
    BMTClientListView,
    CentreAdminAllocationView,
    ClientCreateView,
    ClientDetailView,
    ClientListView,
    ClientUpdateView,
    DeceasedClientListView,
    InvestigationCreateView,
    InvestigationUpdateView,
    TransfusionCreateView,
    TransfusionUpdateView,
    admission_discharge_view,
    client_admissions_partial_view,
    client_investigations_partial_view,
    load_districts_view,
    load_ds_divisions_view,
)

app_name = "clients"

urlpatterns = [
    path("", ClientListView.as_view(), name="client-list"),
    path("centre-admin/", CentreAdminAllocationView.as_view(), name="centre-admin"),
    path("deceased/", DeceasedClientListView.as_view(), name="client-deceased-list"),
    path("bmt/", BMTClientListView.as_view(), name="client-bmt-list"),
    path("create/", ClientCreateView.as_view(), name="client-create"),
    path("<int:pk>/", ClientDetailView.as_view(), name="client-detail"),
    path("<int:pk>/edit/", ClientUpdateView.as_view(), name="client-update"),
    # Admissions & Transfusions routes
    path("<int:client_id>/admissions/create/", AdmissionCreateView.as_view(), name="admission-create"),
    path("<int:client_id>/admissions/partial/", client_admissions_partial_view, name="admissions-partial"),
    path("admissions/<int:pk>/edit/", AdmissionUpdateView.as_view(), name="admission-update"),
    path("admissions/<int:pk>/discharge/", admission_discharge_view, name="admission-discharge"),
    path("admissions/<int:admission_id>/transfusions/create/", TransfusionCreateView.as_view(), name="transfusion-create"),
    path("transfusions/<int:pk>/edit/", TransfusionUpdateView.as_view(), name="transfusion-update"),
    # Investigations routes
    path("<int:client_id>/investigations/create/", InvestigationCreateView.as_view(), name="investigation-create"),
    path("<int:client_id>/investigations/partial/", client_investigations_partial_view, name="investigations-partial"),
    path("investigations/<int:pk>/edit/", InvestigationUpdateView.as_view(), name="investigation-update"),
    # HTMX location cascading endpoints
    path("load-districts/", load_districts_view, name="load-districts"),
    path("load-ds-divisions/", load_ds_divisions_view, name="load-ds-divisions"),
]
