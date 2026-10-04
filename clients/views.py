from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from .forms import AdmissionForm, ClientForm, InvestigationForm, TransfusionForm
from .models import Admission, Client, ClientCareUnit, District, DS_Division, Investigation, Transfusion


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


from users.permissions import UnitScopedClientPermissionMixin, UnitScopedQuerySetMixin, can_user_edit_entry


# -------------------------------------------------------------------
#                       CLIENT CRUD VIEWS
# -------------------------------------------------------------------
class ClientListView(LoginRequiredMixin, UnitScopedClientPermissionMixin, ListView):
    """Searchable & Filterable Client Directory (Scoped to User's Primary Unit)."""

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


class ClientDetailView(LoginRequiredMixin, UnitScopedClientPermissionMixin, DetailView):
    """Comprehensive Patient Profile View (Scoped to User's Primary Unit)."""

    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.object

        # Fetch clinical histories
        context["care_units"] = client.care_links.select_related("unit").all()
        
        # Admissions summary (Top 5 recent by default)
        total_admissions_count = client.client_admissions.count()
        admissions = list(
            client.client_admissions.prefetch_related("blood_transfusions").order_by("-date_of_admission")[:5]
        )
        context["admissions"] = admissions
        context["total_admissions_count"] = total_admissions_count
        context["has_more_admissions"] = total_admissions_count > len(admissions)
        context["next_admissions_limit"] = 10
        context["current_admissions_limit"] = 5

        context["clinic_visits"] = client.clinic_visits.select_related("clinic_type").order_by("-date_visit")

        # Lab Investigations summary (Top 5 recent by default in main card)
        all_investigations = list(client.client_investigations.select_related("investigation_type", "laboratory").order_by("-date_done", "-id"))
        total_investigations_count = len(all_investigations)
        investigations = all_investigations[:5]
        context["investigations"] = investigations
        context["total_investigations_count"] = total_investigations_count
        context["has_more_investigations"] = total_investigations_count > len(investigations)
        context["next_investigations_limit"] = 10
        context["current_investigations_limit"] = 5

        # Extract latest result per investigation type for quick sidebar display & surveillance status
        latest_inv_map = {}
        for inv in all_investigations:
            if inv.investigation_type and inv.investigation_type_id not in latest_inv_map:
                latest_inv_map[inv.investigation_type_id] = inv
        
        latest_list = list(latest_inv_map.values())
        context["latest_investigations"] = latest_list

        # Extract overdue and due soon periodic surveillance alerts
        overdue_investigations = []
        due_soon_investigations = []
        for inv in latest_list:
            status_info = inv.surveillance_status
            if status_info:
                if status_info.get("is_overdue"):
                    overdue_investigations.append(inv)
                elif status_info.get("is_due_soon"):
                    due_soon_investigations.append(inv)

        context["overdue_investigations"] = overdue_investigations
        context["due_soon_investigations"] = due_soon_investigations

        context["growth_records"] = client.growth_records.select_related("type").order_by("-date_measured")
        context["vaccinations"] = client.vaccinations.select_related("vaccine_name").order_by("-date_given")
        context["complications"] = client.client_complications.select_related("complication", "status").order_by("-detected_date")
        context["family_members"] = client.family_members.select_related("diagnosis", "related_client").all()
        context["transfer_records"] = client.transfer_record.select_related("transferred_unit").all()

        return context


class ClientCreateView(LoginRequiredMixin, UnitScopedClientPermissionMixin, CreateView):
    """Client Registration View (Auto-assigns user's Primary Care Unit)."""

    model = Client
    form_class = ClientForm
    template_name = "clients/client_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        client = self.object

        # Auto-assign logged-in user's primary unit if set
        user_unit = getattr(self.request.user, "primary_unit", None)
        if user_unit:
            ClientCareUnit.objects.get_or_create(
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


class ClientUpdateView(LoginRequiredMixin, UnitScopedClientPermissionMixin, UpdateView):
    """Client Profile Update View (Scoped to User's Primary Unit)."""

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


# -------------------------------------------------------------------
#                 ADMISSION & TRANSFUSION CRUD VIEWS
# -------------------------------------------------------------------
def client_admissions_partial_view(request, client_id):
    """HTMX partial returning updated Admissions & Transfusions card with limit/pagination support."""
    if not request.user.is_authenticated:
        raise PermissionDenied()
    client = get_object_or_404(Client, pk=client_id)
    if not request.user.is_system_admin:
        if not request.user.primary_unit or not client.care_links.filter(unit=request.user.primary_unit, is_active=True).exists():
            raise PermissionDenied("You do not have permission to access clients outside your primary unit.")
    total_admissions_count = client.client_admissions.count()
    limit_param = request.GET.get("limit", "5")

    qs = client.client_admissions.prefetch_related("blood_transfusions").order_by("-date_of_admission")

    if limit_param == "all":
        admissions = list(qs)
        current_limit = "all"
        has_more = False
        next_limit = None
    else:
        try:
            limit_num = max(1, int(limit_param))
        except (ValueError, TypeError):
            limit_num = 5
        admissions = list(qs[:limit_num])
        current_limit = limit_num
        has_more = total_admissions_count > len(admissions)
        next_limit = limit_num + 5

    context = {
        "client": client,
        "admissions": admissions,
        "total_admissions_count": total_admissions_count,
        "current_admissions_limit": current_limit,
        "has_more_admissions": has_more,
        "next_admissions_limit": next_limit,
    }
    return render(request, "clients/partials/admissions_list_partial.html", context)


class AdmissionCreateView(LoginRequiredMixin, CreateView):
    """Log a new hospital ward admission for a patient."""

    model = Admission
    form_class = AdmissionForm
    template_name = "clients/modals/admission_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        self.client_obj = get_object_or_404(Client, pk=self.kwargs["client_id"])
        if not request.user.is_system_admin:
            if not request.user.primary_unit or not self.client_obj.care_links.filter(unit=request.user.primary_unit, is_active=True).exists():
                raise PermissionDenied("You do not have permission to log admissions for clients outside your primary unit.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.client = self.client_obj
        admission = form.save()
        messages.success(self.request, f"Admission logged for {self.client_obj.full_name}.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadAdmissions"
            return response
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["client"] = self.client_obj
        context["modal_title"] = f"Log Admission - {self.client_obj.initials_with_last_name}"
        return context


class AdmissionUpdateView(LoginRequiredMixin, UnitScopedQuerySetMixin, UpdateView):
    """Edit or discharge an admission."""

    model = Admission
    form_class = AdmissionForm
    template_name = "clients/modals/admission_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        admission = self.get_object()
        if not can_user_edit_entry(request.user, admission, window_hours=48):
            msg = "Editing admission records older than 48 hours requires Unit Admin or Doctor approval."
            if request.headers.get("HX-Request"):
                return render(request, "clients/modals/permission_denied_modal.html", {"message": msg, "modal_title": "Editing Restricted"})
            raise PermissionDenied(msg)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        admission = form.save()
        messages.success(self.request, "Admission record updated.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadAdmissions"
            return response
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["client"] = self.object.client
        context["modal_title"] = f"Edit Admission - {self.object.client.initials_with_last_name}"
        return context


class TransfusionCreateView(LoginRequiredMixin, CreateView):
    """Log a blood transfusion under a specific hospital admission."""

    model = Transfusion
    form_class = TransfusionForm
    template_name = "clients/modals/transfusion_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        self.admission_obj = get_object_or_404(Admission, pk=self.kwargs["admission_id"])
        if not request.user.is_system_admin:
            if not request.user.primary_unit or not self.admission_obj.client.care_links.filter(unit=request.user.primary_unit, is_active=True).exists():
                raise PermissionDenied("You do not have permission to log transfusions for clients outside your primary unit.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.admission = self.admission_obj
        transfusion = form.save()
        messages.success(self.request, "Blood transfusion logged successfully.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadAdmissions"
            return response
        return super().form_valid(form)

    def get_success_url(self):
        return self.admission_obj.client.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admission"] = self.admission_obj
        context["client"] = self.admission_obj.client
        context["modal_title"] = f"Log Transfusion - {self.admission_obj.client.initials_with_last_name}"
        return context


class TransfusionUpdateView(LoginRequiredMixin, UnitScopedQuerySetMixin, UpdateView):
    """Edit a transfusion record."""

    model = Transfusion
    form_class = TransfusionForm
    template_name = "clients/modals/transfusion_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        transfusion = self.get_object()
        if not can_user_edit_entry(request.user, transfusion, window_hours=48):
            msg = "Editing transfusion records older than 48 hours requires Unit Admin or Doctor approval."
            if request.headers.get("HX-Request"):
                return render(request, "clients/modals/permission_denied_modal.html", {"message": msg, "modal_title": "Editing Restricted"})
            raise PermissionDenied(msg)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        transfusion = form.save()
        messages.success(self.request, "Transfusion record updated.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadAdmissions"
            return response
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.admission.client.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["admission"] = self.object.admission
        context["client"] = self.object.admission.client
        context["modal_title"] = f"Edit Transfusion - {self.object.admission.client.initials_with_last_name}"
        return context


# -------------------------------------------------------------------
#                     INVESTIGATION CRUD VIEWS
# -------------------------------------------------------------------
def client_investigations_partial_view(request, client_id):
    """HTMX partial returning updated Investigations list card with limit/pagination support."""
    if not request.user.is_authenticated:
        raise PermissionDenied()
    client = get_object_or_404(Client, pk=client_id)
    if not request.user.is_system_admin:
        if not request.user.primary_unit or not client.care_links.filter(unit=request.user.primary_unit, is_active=True).exists():
            raise PermissionDenied("You do not have permission to access clients outside your primary unit.")
    qs = client.client_investigations.select_related("investigation_type", "laboratory").order_by("-date_done", "-id")
    total_investigations_count = qs.count()
    limit_param = request.GET.get("limit", "5")

    if limit_param == "all":
        investigations = list(qs)
        current_limit = "all"
        has_more = False
        next_limit = None
    else:
        try:
            limit_num = max(1, int(limit_param))
        except (ValueError, TypeError):
            limit_num = 5
        investigations = list(qs[:limit_num])
        current_limit = limit_num
        has_more = total_investigations_count > len(investigations)
        next_limit = limit_num + 5

    context = {
        "client": client,
        "investigations": investigations,
        "total_investigations_count": total_investigations_count,
        "current_investigations_limit": current_limit,
        "has_more_investigations": has_more,
        "next_investigations_limit": next_limit,
    }
    return render(request, "clients/partials/investigations_list_partial.html", context)


class InvestigationCreateView(LoginRequiredMixin, CreateView):
    """Log a new lab investigation for a patient."""

    model = Investigation
    form_class = InvestigationForm
    template_name = "clients/modals/investigation_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        self.client_obj = get_object_or_404(Client, pk=self.kwargs["client_id"])
        if not request.user.is_system_admin:
            if not request.user.primary_unit or not self.client_obj.care_links.filter(unit=request.user.primary_unit, is_active=True).exists():
                raise PermissionDenied("You do not have permission to log investigations for clients outside your primary unit.")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.client = self.client_obj
        investigation = form.save()
        messages.success(self.request, f"Lab investigation logged for {self.client_obj.full_name}.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadInvestigations"
            return response
        return super().form_valid(form)

    def get_success_url(self):
        return self.client_obj.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["client"] = self.client_obj
        context["modal_title"] = f"Log Investigation - {self.client_obj.initials_with_last_name}"
        return context


class InvestigationUpdateView(LoginRequiredMixin, UnitScopedQuerySetMixin, UpdateView):
    """Edit an existing lab investigation record."""

    model = Investigation
    form_class = InvestigationForm
    template_name = "clients/modals/investigation_form_modal.html"

    def dispatch(self, request, *args, **kwargs):
        investigation = self.get_object()
        if not can_user_edit_entry(request.user, investigation, window_hours=48):
            msg = "Editing investigation records older than 48 hours requires Unit Admin or Doctor approval."
            if request.headers.get("HX-Request"):
                return render(request, "clients/modals/permission_denied_modal.html", {"message": msg, "modal_title": "Editing Restricted"})
            raise PermissionDenied(msg)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        investigation = form.save()
        messages.success(self.request, f"Investigation record updated for {investigation.client.full_name}.")

        if self.request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadInvestigations"
            return response
        return super().form_valid(form)

    def get_success_url(self):
        return self.object.client.get_absolute_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["client"] = self.object.client
        context["modal_title"] = f"Edit Investigation - {self.object.client.initials_with_last_name}"
        return context

