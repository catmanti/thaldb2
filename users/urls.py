from django.urls import path

from .views import (
    CustomLoginView,
    CustomLogoutView,
    dashboard_view,
    update_preferences_view,
)

urlpatterns = [
    path("", dashboard_view, name="dashboard"),
    path("login/", CustomLoginView.as_view(), name="login"),
    path("logout/", CustomLogoutView.as_view(), name="logout"),
    path("dashboard/", dashboard_view, name="dashboard"),
    path("update-preferences/", update_preferences_view, name="update_preferences"),
]
