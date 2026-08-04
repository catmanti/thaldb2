from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import ClientForm
from .models import Client, ClientCareUnit, District, DS_Division


# -------------------------------------------------------------------
#                     HTMX CASCADING LOCATION ENDPOINTS
# -------------------------------------------------------------------
def load_districts_view(request):
    """HTMX endpoint returning District dropdown options for a selected Province."""
    province_id = request.GET.get("province")
    districts = District.objects.filter(province_id=province_id).order_by("name") if province_id else District.objects.none()
    options = ['<option value="">-- Select District --</option>']
    for d in districts:
        options.append(f'<option value="{d.id}">{d.name}</option>')
    return HttpResponse("".join(options))


def load_ds_divisions_view(request):
    """HTMX endpoint returning DS Division dropdown options for a selected District."""
    district_id = request.GET.get("district")
    ds_divisions = DS_Division.objects.filter(district_id=district_id).order_by("name") if district_id else DS_Division.objects.none()
    options = ['<option value="">-- Select DS Division --</option>']
    for ds in ds_divisions:
        options.append(f'<option value="{ds.id}">{ds.name}</option>')
    return HttpResponse("".join(options))


# -------------------------------------------------------------------
#                       CLIENT CRUD VIEWS
# -------------------------------------------------------------------
class ClientListView(LoginRequiredMixin, ListView):
    """Searchable & Filterable Client Directory."""

    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    paginate_by = 15

    def get_queryset(self):
        queryset = super().get_queryset().select_related("diagnosis", "ds_division")
        q = self.request.GET.get("q", "").strip()
        diagnosis_id = self.request.GET.get("diagnosis")
        gender = self.request.GET.get("gender")

        if q:
            queryset = queryset.filter(
                models.Q(registration_number__icontains=q)
                | models.Q(full_name__icontains=q)
                | models.Q(common_name__icontains=q)
                | models.Q(nic_number__icontains=q)
                | models.Q(contact_number__icontains=q)
            )

        if diagnosis_id:
            queryset = queryset.filter(diagnosis_id=diagnosis_id)

        if gender:
            queryset = queryset.filter(gender=gender)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import DiagnosisType

        context["query"] = self.request.GET.get("q", "")
        context["selected_diagnosis"] = self.request.GET.get("diagnosis", "")
        context["selected_gender"] = self.request.GET.get("gender", "")
        context["diagnoses"] = DiagnosisType.objects.all()
        return context


class ClientDetailView(LoginRequiredMixin, DetailView):
    """Comprehensive Patient Profile View."""

    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.object

        # Fetch clinical histories
        context["care_units"] = client.care_links.select_related("unit").all()
        context["admissions"] = client.client_admissions.prefetch_related("blood_transfusions").order_by("-date_of_admission")
        context["clinic_visits"] = client.clinic_visits.select_related("clinic_type").order_by("-date_visit")
        context["investigations"] = client.client_investigations.select_related("investigation_type").order_by("-date_done")
        context["growth_records"] = client.growth_records.select_related("type").order_by("-date_measured")
        context["vaccinations"] = client.vaccinations.select_related("vaccine_name").order_by("-date_given")
        context["complications"] = client.client_complications.select_related("complication", "status").order_by("-detected_date")
        context["family_members"] = client.family_members.select_related("diagnosis", "related_client").all()
        context["transfer_records"] = client.transfer_record.select_related("transferred_unit").all()

        return context


class ClientCreateView(LoginRequiredMixin, CreateView):
    """Client Registration View."""

    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        client = self.object

        # Auto-assign logged-in user's primary unit if set
        user_unit = getattr(self.request.user, "primary_unit", None)
        if user_unit:
            ClientCareUnit.objects.create(
                client=client,
                unit=user_unit,
                role=ClientCareUnit.Role.PRIMARY,
                is_active=True,
            )

        messages.success(self.request, f"Patient '{client.full_name}' ({client.registration_number}) registered successfully!")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Register New Client"
        return context


class ClientUpdateView(LoginRequiredMixin, UpdateView):
    """Client Profile Update View."""

    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Patient profile for '{self.object.full_name}' updated successfully!")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit Client: {self.object.full_name}"
        return context
