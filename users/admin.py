from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _

from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Custom UserAdmin for email-based custom User model."""

    ordering = ["email"]
    list_display = ["email", "first_name", "last_name", "role", "primary_unit", "is_staff", "is_active"]
    list_filter = ["role", "is_staff", "is_superuser", "is_active", "primary_unit"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (
            _("Role & Organization"),
            {
                "fields": (
                    "role",
                    "primary_unit",
                )
            },
        ),
        (
            _("UI Preferences"),
            {
                "fields": (
                    "dark_mode",
                    "color_scheme",
                    "preferences",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "password1",
                    "password2",
                    "first_name",
                    "last_name",
                    "role",
                    "primary_unit",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    search_fields = ["email", "first_name", "last_name"]
