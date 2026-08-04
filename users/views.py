from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as DjangoLoginView, LogoutView as DjangoLogoutView
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST


class CustomLoginView(DjangoLoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True


class CustomLogoutView(DjangoLogoutView):
    next_page = "login"


@login_required
def dashboard_view(request):
    """Main dashboard view."""
    return render(request, "dashboard.html")


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
