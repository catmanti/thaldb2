import datetime
from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from .models import User


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin for Class-Based Views to restrict access based on allowed user roles.
    
    Usage:
        class SensitiveView(RoleRequiredMixin, TemplateView):
            allowed_roles = [User.Role.DOCTOR, User.Role.UNIT_ADMIN]
    """
    allowed_roles: list = []

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser or user.role == User.Role.SYSTEM_ADMIN:
            return True
        return user.role in self.allowed_roles

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("You do not have permission to access this resource.")
        return super().handle_no_permission()


class DoctorRequiredMixin(RoleRequiredMixin):
    """Restricts access to Doctors and System Admins."""
    allowed_roles = [User.Role.DOCTOR, User.Role.SYSTEM_ADMIN]


class UnitAdminRequiredMixin(RoleRequiredMixin):
    """Restricts access to Unit Administrators and System Admins."""
    allowed_roles = [User.Role.UNIT_ADMIN, User.Role.SYSTEM_ADMIN]


class ClinicalStaffRequiredMixin(RoleRequiredMixin):
    """Restricts access to clinical staff (Doctors, Nurses, Unit Admins, System Admins)."""
    allowed_roles = [
        User.Role.DOCTOR,
        User.Role.NURSE,
        User.Role.UNIT_ADMIN,
        User.Role.SYSTEM_ADMIN,
    ]


class UnitScopedQuerySetMixin:
    """
    Mixin for Class-Based Views to automatically filter querysets based on 
    the logged-in user's primary unit.
    
    System Administrators can view all records. Staff with an assigned primary unit
    will only see records linked to their unit.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)
        
        if not user or not user.is_authenticated:
            return qs.none()
            
        # System Admin or superuser gets unrestricted access across all units
        if user.is_system_admin or user.is_superuser:
            return qs

        # Filter by primary_unit if defined on user
        if user.primary_unit:
            model_name = qs.model.__name__
            if model_name == "Client":
                return qs.filter(care_links__unit=user.primary_unit, care_links__is_active=True).distinct()
            elif hasattr(qs.model, "client"):
                return qs.filter(client__care_links__unit=user.primary_unit, client__care_links__is_active=True).distinct()
            elif hasattr(qs.model, "admission"):
                return qs.filter(admission__client__care_links__unit=user.primary_unit, admission__client__care_links__is_active=True).distinct()

        return qs


def can_user_edit_entry(user: User, entry, window_hours: int = 48) -> bool:
    """
    Determines if a user has permission to edit a clinical entry (Admission, Transfusion, Lab Result).
    
    - System Admins, Unit Admins, and Doctors can edit at any time.
    - Data Entry Clerks and Nurses can edit entries within `window_hours` (default 48 hours) 
      of creation or event date. Beyond 48 hours, edit permissions escalate to Unit Admin/Doctor.
    """
    if not user or not user.is_authenticated:
        return False

    # Elevated roles can edit any entry
    if user.is_unit_admin or user.is_doctor or user.is_system_admin:
        return True

    # Determine timestamp of creation or event
    timestamp = getattr(entry, "created_at", None)
    if not timestamp:
        # Fallback to date fields if created_at is not present
        date_val = getattr(entry, "date_done", None) or getattr(entry, "date_of_admission", None) or getattr(entry, "date_of_transfusion", None)
        if date_val:
            timestamp = timezone.make_aware(datetime.datetime.combine(date_val, datetime.time.min))

    if not timestamp:
        return True

    # Check if entry creation is within the allowed window
    cutoff = timezone.now() - datetime.timedelta(hours=window_hours)
    return timestamp >= cutoff
