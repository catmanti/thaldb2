from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from clients.models import Admission, Client, ClinicVisit, ThalassemiaUnit, Transfusion


class CustomLoginView(DjangoLoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True


class CustomLogoutView(DjangoLogoutView):
    next_page = "login"


@login_required
def dashboard_view(request):
    """Main role-customized dashboard view (Scoped by Unit for staff, Global for System Admins)."""
    user = request.user

    if user.is_system_admin or user.is_superuser:
        clients_qs = Client.objects.all()
        admissions_qs = Admission.objects.all()
        transfusions_qs = Transfusion.objects.all()
        visits_qs = ClinicVisit.objects.select_related("client", "clinic_type").all()
    elif user.primary_unit:
        clients_qs = Client.objects.filter(care_links__unit=user.primary_unit, care_links__is_active=True).distinct()
        admissions_qs = Admission.objects.filter(client__care_links__unit=user.primary_unit, client__care_links__is_active=True).distinct()
        transfusions_qs = Transfusion.objects.filter(admission__client__care_links__unit=user.primary_unit, admission__client__care_links__is_active=True).distinct()
        visits_qs = ClinicVisit.objects.filter(client__care_links__unit=user.primary_unit, client__care_links__is_active=True).select_related("client", "clinic_type").distinct()
    else:
        clients_qs = Client.objects.none()
        admissions_qs = Admission.objects.none()
        transfusions_qs = Transfusion.objects.none()
        visits_qs = ClinicVisit.objects.none()

    total_clients = clients_qs.count()
    total_admissions = admissions_qs.count()
    total_transfusions = transfusions_qs.count()
    total_units = ThalassemiaUnit.objects.count()

    recent_clients = clients_qs.select_related("diagnosis").order_by("-id")[:5]
    recent_visits = visits_qs.order_by("-date_visit")[:5]

    context = {
        "total_clients": total_clients,
        "total_admissions": total_admissions,
        "total_transfusions": total_transfusions,
        "total_units": total_units,
        "recent_clients": recent_clients,
        "recent_visits": recent_visits,
        "user_primary_unit": user.primary_unit,
    }
    return render(request, "dashboard.html", context)


@login_required
@require_POST
def update_preferences_view(request):
    """HTMX / AJAX endpoint to update user theme and dark mode settings."""
    user = request.user
    color_scheme = request.POST.get("color_scheme")
    dark_mode = request.POST.get("dark_mode")

    updated = False
    if color_scheme and color_scheme in [c[0] for c in user.COLOR_SCHEME_CHOICES]:
        user.color_scheme = color_scheme
        user.dark_mode = (color_scheme == "dark")
        updated = True

    if dark_mode is not None:
        is_dark = dark_mode.lower() in ("true", "1", "yes")
        user.dark_mode = is_dark
        user.color_scheme = "dark" if is_dark else "light"
        updated = True

    if updated:
        user.save()
        return JsonResponse({"status": "success", "color_scheme": user.color_scheme, "dark_mode": user.dark_mode})

    return JsonResponse({"status": "no_change"})
