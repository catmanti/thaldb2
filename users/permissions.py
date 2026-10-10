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

        return qs.none()


class UnitScopedClientPermissionMixin(UserPassesTestMixin):
    """
    Enforces strict unit-level permission isolation on Client views:
    - System Admins can view/edit clients across all units.
    - Other users can only view/edit clients linked to their primary_unit.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        user = getattr(self.request, "user", None)

        if not user or not user.is_authenticated:
            return qs.none()

        if user.is_system_admin or user.is_superuser:
            return qs

        if user.primary_unit:
            return qs.filter(care_links__unit=user.primary_unit).distinct()

        return qs.none()

    def test_func(self) -> bool:
        user = getattr(self.request, "user", None)
        if not user or not user.is_authenticated:
            return False

        if user.is_system_admin or user.is_superuser:
            return True

        if not user.primary_unit:
            return False

        # For single object views (DetailView, UpdateView), check object-level access
        if hasattr(self, "get_object"):
            try:
                client = self.get_object()
                return client.care_links.filter(unit=user.primary_unit).exists()
            except Exception:
                pass

        return True

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("You do not have permission to access clients outside your assigned primary unit.")
        return super().handle_no_permission()



def can_user_edit_entry(user: User, entry, window_hours: int = 48) -> bool:
    """
    Determines if a user has permission to edit a clinical entry (Admission, Transfusion, Lab Result).
    
    - System Admins, Unit Admins, and Doctors can edit at any time.
    - Data Entry Clerks and Nurses can edit entries within `window_hours` (default 48 hours) 
      of creation AND event date. Beyond 48 hours, edit permissions escalate to Unit Admin/Doctor.
    """
    if not user or not user.is_authenticated:
        return False

    # Elevated roles can edit any entry
    if user.is_unit_admin or user.is_doctor or user.is_system_admin:
        return True

    cutoff = timezone.now() - datetime.timedelta(hours=window_hours)

    # 1. Check clinical event date (date_of_transfusion, date_of_admission, date_done)
    event_date = getattr(entry, "date_done", None) or getattr(entry, "date_of_admission", None) or getattr(entry, "date_of_transfusion", None)
    if event_date:
        if isinstance(event_date, str):
            try:
                event_date = datetime.date.fromisoformat(event_date)
            except ValueError:
                event_date = None

        if isinstance(event_date, datetime.date) and not isinstance(event_date, datetime.datetime):
            event_dt = timezone.make_aware(datetime.datetime.combine(event_date, datetime.time.max))
        elif isinstance(event_date, datetime.datetime):
            event_dt = event_date if timezone.is_aware(event_date) else timezone.make_aware(event_date)
        else:
            event_dt = None

        if event_dt and event_dt < cutoff:
            return False

    # 2. Check database creation timestamp
    created_at = getattr(entry, "created_at", None)
    if created_at and created_at < cutoff:
        return False

    return True
