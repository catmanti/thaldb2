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
    """Main role-customized dashboard view."""
    total_clients = Client.objects.count()
    total_admissions = Admission.objects.count()
    total_transfusions = Transfusion.objects.count()
    total_units = ThalassemiaUnit.objects.count()

    recent_clients = Client.objects.select_related("diagnosis").order_by("-id")[:5]
    recent_visits = ClinicVisit.objects.select_related("client", "clinic_type").order_by("-date_visit")[:5]

    context = {
        "total_clients": total_clients,
        "total_admissions": total_admissions,
        "total_transfusions": total_transfusions,
        "total_units": total_units,
        "recent_clients": recent_clients,
        "recent_visits": recent_visits,
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
        updated = True

    if dark_mode is not None:
        user.dark_mode = dark_mode.lower() in ("true", "1", "yes")
        updated = True

    if updated:
        user.save()
        return JsonResponse({"status": "success", "color_scheme": user.color_scheme, "dark_mode": user.dark_mode})

    return JsonResponse({"status": "no_change"})
