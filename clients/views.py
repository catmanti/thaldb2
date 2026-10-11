from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from django.contrib.auth import get_user_model
from django.utils import timezone

from .forms import AdmissionForm, ClientForm, DoctorCoverageForm, InvestigationForm, TransfusionForm
from .models import (
    Admission,
    Client,
    ClientCareAssignment,
    ClientCareUnit,
    District,
    DoctorCoverage,
    DS_Division,
    Investigation,
    ThalassemiaUnit,
    Transfusion,
)
from .utils import build_client_search_query


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


from users.permissions import (
    ClinicalStaffRequiredMixin,
    UnitAdminRequiredMixin,
    UnitScopedClientPermissionMixin,
    UnitScopedQuerySetMixin,
    can_user_edit_entry,
)


# -------------------------------------------------------------------
#                       CLIENT CRUD VIEWS
# -------------------------------------------------------------------
class ClientListView(LoginRequiredMixin, UnitScopedClientPermissionMixin, ListView):
    """Searchable & Filterable Client Directory (Scoped to User's Primary Unit and Doctor Caseload)."""

    model = Client
    template_name = "clients/client_list.html"
    context_object_name = "clients"
    DEFAULT_PAGE_SIZE = 50
    ALLOWED_PAGE_SIZES = [25, 50, 100]

    def get_paginate_by(self, queryset):
        page_size_param = self.request.GET.get("page_size")
        if page_size_param and page_size_param.isdigit():
            size = int(page_size_param)
            if size in self.ALLOWED_PAGE_SIZES:
                return size
        return self.DEFAULT_PAGE_SIZE

    def get_queryset(self):
        user = self.request.user
        today = timezone.localdate()

        active_care_units_prefetch = models.Prefetch(
            "care_links",
            queryset=ClientCareUnit.objects.filter(is_active=True, role=ClientCareUnit.Role.PRIMARY).select_related("unit"),
        )
        active_doctor_prefetch = models.Prefetch(
            "doctor_assignments",
            queryset=ClientCareAssignment.objects.filter(valid_to__isnull=True).select_related("doctor"),
            to_attr="active_doctor_assignment_list",
        )

        queryset = (
            super()
            .get_queryset()
            .filter(care_links__is_active=True)
            .distinct()
            .select_related("diagnosis", "ds_division")
            .prefetch_related(active_care_units_prefetch, active_doctor_prefetch)
        )

        # Active cross-coverage check for doctor
        covered_doctor_ids = []
        if user.is_authenticated and user.is_doctor:
            covered_doctor_ids = list(
                DoctorCoverage.objects.filter(
                    covering_doctor=user,
                    start_date__lte=today,
                    end_date__gte=today,
                    is_active=True,
                ).values_list("absent_doctor_id", flat=True)
            )

        # Doctor Filter logic
        doctor_filter = self.request.GET.get("doctor")
        if doctor_filter is None:
            doctor_filter = "me" if (user.is_authenticated and user.is_doctor) else "all"

        if doctor_filter == "me" and user.is_authenticated:
            queryset = queryset.filter(doctor_assignments__doctor=user, doctor_assignments__valid_to__isnull=True)
        elif doctor_filter == "covering" and user.is_authenticated:
            if covered_doctor_ids:
                queryset = queryset.filter(
                    doctor_assignments__doctor_id__in=covered_doctor_ids,
                    doctor_assignments__valid_to__isnull=True,
                )
            else:
                queryset = queryset.none()
        elif doctor_filter == "unassigned":
            active_assigned_ids = ClientCareAssignment.objects.filter(valid_to__isnull=True).values("client_id")
            queryset = queryset.exclude(id__in=active_assigned_ids)
        elif doctor_filter and doctor_filter != "all" and doctor_filter.isdigit():
            queryset = queryset.filter(
                doctor_assignments__doctor_id=int(doctor_filter),
                doctor_assignments__valid_to__isnull=True,
            )

        q = self.request.GET.get("q", "").strip()
        diagnosis_id = self.request.GET.get("diagnosis")
        gender = self.request.GET.get("gender")

        if q:
            queryset = queryset.filter(build_client_search_query(q))

        if diagnosis_id:
            queryset = queryset.filter(diagnosis_id=diagnosis_id)

        if gender:
            queryset = queryset.filter(gender=gender)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import DiagnosisType

        User = get_user_model()
        user = self.request.user
        today = timezone.localdate()

        doctor_filter = self.request.GET.get("doctor")
        if doctor_filter is None:
            doctor_filter = "me" if (user.is_authenticated and user.is_doctor) else "all"

        # Base active client queryset for badge counters
        base_unit_qs = Client.objects.filter(care_links__is_active=True)
        if not (user.is_system_admin or user.is_superuser) and user.primary_unit:
            base_unit_qs = base_unit_qs.filter(care_links__unit=user.primary_unit).distinct()

        # Doctors at this care unit for filter dropdown
        if user.primary_unit:
            unit_doctors = User.objects.filter(role=User.Role.DOCTOR, primary_unit=user.primary_unit, is_active=True).order_by("first_name", "last_name")
        else:
            unit_doctors = User.objects.filter(role=User.Role.DOCTOR, is_active=True).order_by("first_name", "last_name")

        covered_doctor_ids = []
        if user.is_authenticated and user.is_doctor:
            covered_doctor_ids = list(
                DoctorCoverage.objects.filter(
                    covering_doctor=user,
                    start_date__lte=today,
                    end_date__gte=today,
                    is_active=True,
                ).values_list("absent_doctor_id", flat=True)
            )

        context["query"] = self.request.GET.get("q", "")
        context["selected_diagnosis"] = self.request.GET.get("diagnosis", "")
        context["selected_gender"] = self.request.GET.get("gender", "")
        context["selected_doctor"] = doctor_filter
        context["diagnoses"] = DiagnosisType.objects.all()
        context["unit_doctors"] = unit_doctors
        context["has_covering_duty"] = bool(covered_doctor_ids)

        # Tab badge counts
        active_assigned_ids = ClientCareAssignment.objects.filter(valid_to__isnull=True).values("client_id")
        context["all_patients_count"] = base_unit_qs.count()
        context["unassigned_patients_count"] = base_unit_qs.exclude(id__in=active_assigned_ids).count()
        if user.is_authenticated and user.is_doctor:
            context["my_patients_count"] = base_unit_qs.filter(doctor_assignments__doctor=user, doctor_assignments__valid_to__isnull=True).count()
            context["covering_patients_count"] = (
                base_unit_qs.filter(doctor_assignments__doctor_id__in=covered_doctor_ids, doctor_assignments__valid_to__isnull=True).count()
                if covered_doctor_ids
                else 0
            )

        context["page_size"] = self.get_paginate_by(self.object_list)
        context["allowed_page_sizes"] = self.ALLOWED_PAGE_SIZES

        return context


class DeceasedClientListView(LoginRequiredMixin, ListView):
    """Deceased Patients Registry (Scoped to User's Primary Unit for hospital staff)."""

    model = Client
    template_name = "clients/client_deceased_list.html"
    context_object_name = "clients"
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        queryset = (
            Client.objects.filter(death_record__isnull=False)
            .select_related("diagnosis", "ds_division", "death_record")
            .prefetch_related(
                models.Prefetch(
                    "care_links",
                    queryset=ClientCareUnit.objects.select_related("unit").order_by("-is_active", "-start_date"),
                )
            )
        )
        if not (user.is_system_admin or user.is_superuser):
            if user.primary_unit:
                queryset = queryset.filter(care_links__unit=user.primary_unit).distinct()
            else:
                return Client.objects.none()

        q = self.request.GET.get("q", "").strip()
        diagnosis_id = self.request.GET.get("diagnosis")
        gender = self.request.GET.get("gender")

        if q:
            queryset = queryset.filter(build_client_search_query(q, extra_fields=["death_record__cause_of_death"]))

        if diagnosis_id:
            queryset = queryset.filter(diagnosis_id=diagnosis_id)

        if gender:
            queryset = queryset.filter(gender=gender)

        return queryset.order_by("-death_record__date_of_death", "-id")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .models import DiagnosisType

        context["query"] = self.request.GET.get("q", "")
        context["selected_diagnosis"] = self.request.GET.get("diagnosis", "")
        context["selected_gender"] = self.request.GET.get("gender", "")
        context["diagnoses"] = DiagnosisType.objects.all()
        return context


class BMTClientListView(LoginRequiredMixin, ListView):
    """Bone Marrow Transplant Patients Registry (Scoped to User's Primary Unit for hospital staff)."""

    model = Client
    template_name = "clients/client_bmt_list.html"
    context_object_name = "clients"
    paginate_by = 15

    def get_queryset(self):
        user = self.request.user
        queryset = (
            Client.objects.filter(bmt_records__isnull=False)
            .distinct()
            .select_related("diagnosis", "ds_division")
            .prefetch_related(
                "bmt_records",
                models.Prefetch(
                    "care_links",
                    queryset=ClientCareUnit.objects.select_related("unit").order_by("-is_active", "-start_date"),
                ),
            )
        )
        if not (user.is_system_admin or user.is_superuser):
            if user.primary_unit:
                queryset = queryset.filter(care_links__unit=user.primary_unit).distinct()
            else:
                return Client.objects.none()

        q = self.request.GET.get("q", "").strip()
        diagnosis_id = self.request.GET.get("diagnosis")
        gender = self.request.GET.get("gender")

        if q:
            queryset = queryset.filter(
                build_client_search_query(
                    q, extra_fields=["bmt_records__institution_name", "bmt_records__donor_type"]
                )
            )

        if diagnosis_id:
            queryset = queryset.filter(diagnosis_id=diagnosis_id)

        if gender:
            queryset = queryset.filter(gender=gender)

        return queryset.order_by("-id")

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

    def get_queryset(self):
        return super().get_queryset().select_related("diagnosis", "marital_status", "ds_division__district", "death_record")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        client = self.object

        # Fetch clinical care units with unit details (active first, then historical)
        care_links = list(client.care_links.select_related("unit").order_by("-is_active", "-start_date"))
        context["care_units"] = care_links
        # Cache on client instance so client.primary_care_unit does not trigger an extra DB query
        if not hasattr(client, "_prefetched_objects_cache"):
            client._prefetched_objects_cache = {}
        client._prefetched_objects_cache["care_links"] = care_links

        # Admissions summary (Top 5 recent by default, with optimized prefetching)
        transfusions_prefetch = models.Prefetch(
            "blood_transfusions",
            queryset=Transfusion.objects.select_related("special_type").order_by("-date_of_transfusion", "-id"),
        )
        admissions_qs = (
            client.client_admissions.select_related("reason_for_admission")
            .prefetch_related(transfusions_prefetch)
            .order_by("-date_of_admission", "-id")
        )
        total_admissions_count = client.client_admissions.count()
        admissions = list(admissions_qs[:5])
        context["admissions"] = admissions
        context["total_admissions_count"] = total_admissions_count
        context["has_more_admissions"] = total_admissions_count > len(admissions)
        context["next_admissions_limit"] = 10
        context["current_admissions_limit"] = 5

        # Clinic visits (with clinic_type)
        context["clinic_visits"] = client.clinic_visits.select_related("clinic_type").order_by("-date_visit")

        # Lab Investigations summary (Top 5 recent by default in main card)
        all_investigations = list(
            client.client_investigations.select_related("investigation_type", "laboratory").order_by(
                "-date_done", "-id"
            )
        )
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
    transfusions_prefetch = models.Prefetch(
        "blood_transfusions",
        queryset=Transfusion.objects.select_related("special_type").order_by("-date_of_transfusion", "-id"),
    )
    qs = (
        client.client_admissions.select_related("reason_for_admission")
        .prefetch_related(transfusions_prefetch)
        .order_by("-date_of_admission", "-id")
    )

    limit_param = request.GET.get("limit", "5")

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
        # Strategy B: If user opted to close previous unclosed admission, close it cleanly
        if self.request.POST.get("close_previous_admission") in ("true", "on", "1"):
            open_admissions = self.client_obj.client_admissions.filter(date_of_discharge__isnull=True)
            for old_adm in open_admissions:
                old_adm.mark_discharged(
                    discharge_time=form.instance.date_of_admission,
                    outcome="Closed upon new admission",
                )

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
        context["active_admission"] = (
            self.client_obj.client_admissions.filter(date_of_discharge__isnull=True)
            .order_by("-date_of_admission")
            .first()
        )
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


@login_required
def admission_discharge_view(request, pk):
    """Quick-discharge an active admission."""
    admission = get_object_or_404(Admission, pk=pk)
    if not can_user_edit_entry(request.user, admission, window_hours=48):
        raise PermissionDenied("You do not have permission to discharge this admission.")

    if request.method == "POST":
        admission.mark_discharged(outcome="Discharged via Quick-Action")
        messages.success(request, f"Patient {admission.client.full_name} marked as discharged.")
        if request.headers.get("HX-Request"):
            response = HttpResponse("", status=200)
            response["HX-Trigger"] = "reloadAdmissions"
            return response
        return redirect(admission.client.get_absolute_url())

    return HttpResponse(status=405)


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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        form.instance.admission = self.admission_obj
        transfusion = form.save()

        # Strategy C: Auto-discharge for routine day-care admissions upon transfusion recording
        admission = self.admission_obj
        if admission.is_routine_day_transfusion and admission.date_of_discharge is None:
            admission.mark_discharged(
                discharge_time=transfusion.date_of_transfusion,
                outcome="Routine Day-Care Transfusion Completed",
            )

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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

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


# -------------------------------------------------------------------
#                 CENTRE ADMIN: DOCTOR CASELOAD & ALLOCATION
# -------------------------------------------------------------------
class CentreAdminAllocationView(UnitAdminRequiredMixin, ListView):
    """
    Dedicated Centre Administration & Doctor Caseload Management Panel.
    Enables Unit Admins and System Admins to:
    - View live doctor workload distributions (total, male, female, pediatric).
    - Manage temporary leave delegations / cross-coverage.
    - Perform single & smart multi-doctor batch patient allocations.
    """

    model = Client
    template_name = "clients/centre_admin_allocation.html"
    context_object_name = "clients"
    paginate_by = 50

    def get_unit(self):
        user = self.request.user
        unit_id = self.request.GET.get("unit") or self.request.POST.get("unit_id")
        if (user.is_system_admin or user.is_superuser) and unit_id:
            return get_object_or_404(ThalassemiaUnit, pk=unit_id)
        if user.primary_unit:
            return user.primary_unit
        return ThalassemiaUnit.objects.first()

    def get_queryset(self):
        unit = self.get_unit()
        if not unit:
            return Client.objects.none()

        active_assignments_prefetch = models.Prefetch(
            "doctor_assignments",
            queryset=ClientCareAssignment.objects.filter(care_unit=unit, valid_to__isnull=True).select_related("doctor"),
            to_attr="active_doctor_assignment_list",
        )

        qs = (
            Client.objects.filter(care_links__unit=unit, care_links__is_active=True)
            .distinct()
            .select_related("diagnosis", "ds_division")
            .prefetch_related(active_assignments_prefetch)
        )

        status_filter = self.request.GET.get("status", "unassigned")
        gender_filter = self.request.GET.get("gender")
        age_group = self.request.GET.get("age_group")
        doctor_id = self.request.GET.get("doctor")
        q = self.request.GET.get("q", "").strip()

        active_unit_assigned_ids = ClientCareAssignment.objects.filter(care_unit=unit, valid_to__isnull=True).values("client_id")
        if status_filter == "unassigned":
            qs = qs.exclude(id__in=active_unit_assigned_ids)
        elif status_filter == "assigned":
            qs = qs.filter(id__in=active_unit_assigned_ids)

        if doctor_id and doctor_id.isdigit():
            qs = qs.filter(
                doctor_assignments__care_unit=unit,
                doctor_assignments__doctor_id=int(doctor_id),
                doctor_assignments__valid_to__isnull=True,
            )

        if gender_filter:
            qs = qs.filter(gender=gender_filter)

        today = timezone.localdate()
        if age_group == "pediatric":
            cutoff = today.replace(year=today.year - 12)
            qs = qs.filter(date_of_birth__gt=cutoff)
        elif age_group == "adolescent":
            cutoff_18 = today.replace(year=today.year - 18)
            cutoff_12 = today.replace(year=today.year - 12)
            qs = qs.filter(date_of_birth__gte=cutoff_18, date_of_birth__lte=cutoff_12)
        elif age_group == "adult":
            cutoff_18 = today.replace(year=today.year - 18)
            qs = qs.filter(date_of_birth__lt=cutoff_18)

        if q:
            qs = qs.filter(build_client_search_query(q))

        return qs.order_by("registration_number")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        unit = self.get_unit()
        context["care_unit"] = unit
        context["all_units"] = (
            ThalassemiaUnit.objects.all() if (self.request.user.is_system_admin or self.request.user.is_superuser) else []
        )

        if not unit:
            return context

        User = get_user_model()
        today = timezone.localdate()
        cutoff_12 = today.replace(year=today.year - 12)

        doctors = User.objects.filter(role=User.Role.DOCTOR, primary_unit=unit, is_active=True).order_by("first_name", "last_name")
        doctor_stats = []
        for doc in doctors:
            assigned_clients = Client.objects.filter(
                care_links__unit=unit,
                care_links__is_active=True,
                doctor_assignments__care_unit=unit,
                doctor_assignments__doctor=doc,
                doctor_assignments__valid_to__isnull=True,
            ).distinct()

            total_doc = assigned_clients.count()
            male_doc = assigned_clients.filter(gender="M").count()
            female_doc = assigned_clients.filter(gender="F").count()
            ped_doc = assigned_clients.filter(date_of_birth__gt=cutoff_12).count()

            active_coverage = DoctorCoverage.objects.filter(
                care_unit=unit,
                absent_doctor=doc,
                start_date__lte=today,
                end_date__gte=today,
                is_active=True,
            ).first()

            doctor_stats.append({
                "doctor": doc,
                "total": total_doc,
                "male": male_doc,
                "female": female_doc,
                "pediatric": ped_doc,
                "is_on_leave": bool(active_coverage),
                "active_coverage": active_coverage,
            })

        total_unit_clients = Client.objects.filter(care_links__unit=unit, care_links__is_active=True).distinct().count()
        active_unit_assigned_ids = ClientCareAssignment.objects.filter(care_unit=unit, valid_to__isnull=True).values("client_id")
        unassigned_count = (
            Client.objects.filter(care_links__unit=unit, care_links__is_active=True)
            .exclude(id__in=active_unit_assigned_ids)
            .distinct()
            .count()
        )

        coverages = (
            DoctorCoverage.objects.filter(care_unit=unit)
            .select_related("absent_doctor", "covering_doctor")
            .order_by("-start_date", "-id")[:10]
        )

        context["doctor_stats"] = doctor_stats
        context["doctors"] = doctors
        context["total_unit_clients"] = total_unit_clients
        context["unassigned_count"] = unassigned_count
        context["coverages"] = coverages
        context["coverage_form"] = DoctorCoverageForm(care_unit=unit)

        context["selected_status"] = self.request.GET.get("status", "unassigned")
        context["selected_gender"] = self.request.GET.get("gender", "")
        context["selected_age_group"] = self.request.GET.get("age_group", "")
        context["selected_doctor"] = self.request.GET.get("doctor", "")
        context["query"] = self.request.GET.get("q", "")
        return context

    def post(self, request, *args, **kwargs):
        unit = self.get_unit()
        if not unit:
            messages.error(request, "Care unit not found.")
            return redirect("clients:centre-admin")

        action = request.POST.get("action")
        User = get_user_model()

        if action == "assign_doctor":
            client_ids = request.POST.getlist("client_ids")
            doctor_id = request.POST.get("target_doctor_id")
            if not client_ids:
                messages.error(request, "Please select at least one patient to assign.")
                return redirect(request.get_full_path())
            if not doctor_id:
                messages.error(request, "Please select a target doctor.")
                return redirect(request.get_full_path())

            target_doctor = get_object_or_404(User, pk=doctor_id, role=User.Role.DOCTOR)
            clients_to_assign = Client.objects.filter(id__in=client_ids, care_links__unit=unit)

            assigned_count = 0
            for client in clients_to_assign:
                ClientCareAssignment.assign_doctor(
                    client=client,
                    care_unit=unit,
                    doctor=target_doctor,
                    assigned_by=request.user,
                    notes=request.POST.get("assignment_notes", "Batch assignment by Centre Admin"),
                )
                assigned_count += 1

            messages.success(
                request,
                f"Successfully assigned {assigned_count} patient(s) to Dr. {target_doctor.get_full_name() or target_doctor.email}."
            )
            return redirect(request.get_full_path())

        elif action == "smart_split":
            client_ids = request.POST.getlist("client_ids")
            doctor_ids = request.POST.getlist("split_doctor_ids")
            if not client_ids:
                messages.error(request, "Please select at least one patient to distribute.")
                return redirect(request.get_full_path())
            if not doctor_ids or len(doctor_ids) < 2:
                messages.error(request, "Please select at least two doctors to distribute patients evenly between.")
                return redirect(request.get_full_path())

            selected_doctors = list(User.objects.filter(id__in=doctor_ids, role=User.Role.DOCTOR))
            clients_to_assign = list(
                Client.objects.filter(id__in=client_ids, care_links__unit=unit).order_by("registration_number")
            )

            num_docs = len(selected_doctors)
            for i, client in enumerate(clients_to_assign):
                doc = selected_doctors[i % num_docs]
                ClientCareAssignment.assign_doctor(
                    client=client,
                    care_unit=unit,
                    doctor=doc,
                    assigned_by=request.user,
                    notes=f"Evenly distributed across {num_docs} doctors by Centre Admin",
                )

            messages.success(
                request,
                f"Successfully distributed {len(clients_to_assign)} patient(s) evenly across {num_docs} doctors: "
                + ", ".join([f"Dr. {d.get_full_name() or d.email}" for d in selected_doctors])
            )
            return redirect(request.get_full_path())

        elif action == "add_coverage":
            form = DoctorCoverageForm(request.POST, care_unit=unit)
            if form.is_valid():
                cov = form.save(commit=False)
                cov.care_unit = unit
                cov.save()
                messages.success(
                    request,
                    f"Leave coverage scheduled: Dr. {cov.covering_doctor} covering for Dr. {cov.absent_doctor}."
                )
            else:
                err_msg = " ".join([f"{f}: {e[0]}" for f, e in form.errors.items()])
                messages.error(request, f"Could not schedule coverage: {err_msg}")
            return redirect(request.get_full_path())

        elif action == "end_coverage":
            cov_id = request.POST.get("coverage_id")
            cov = get_object_or_404(DoctorCoverage, pk=cov_id, care_unit=unit)
            cov.is_active = False
            cov.save(update_fields=["is_active", "updated_at"])
            messages.success(request, f"Leave coverage for Dr. {cov.absent_doctor} has been deactivated.")
            return redirect(request.get_full_path())

        return redirect(request.get_full_path())

