from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase
from django.urls import reverse

from clients.models import Admission, Client, ThalassemiaUnit, Transfusion

User = get_user_model()


class CustomUserManagerTests(TestCase):
    """Tests for CustomUserManager (email-based authentication)."""

    def test_create_user_success(self):
        user = User.objects.create_user(
            email="nurse@hospital.lk",
            password="securepassword123",
            first_name="Kamal",
            last_name="Perera",
        )
        self.assertEqual(user.email, "nurse@hospital.lk")
        self.assertTrue(user.check_password("securepassword123"))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.role, User.Role.DATA_ENTRY)
        self.assertFalse(user.dark_mode)
        self.assertEqual(user.color_scheme, "light")

    def test_create_user_email_normalized(self):
        user = User.objects.create_user(email="DOCTOR@Hospital.LK", password="pass")
        self.assertEqual(user.email, "DOCTOR@hospital.lk")

    def test_create_user_duplicate_email_raises_integrity_error(self):
        User.objects.create_user(email="duplicate@hospital.lk", password="pass1")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email="duplicate@hospital.lk", password="pass2")

    def test_create_user_without_email_raises_error(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="pass")

    def test_create_superuser_success(self):
        admin_user = User.objects.create_superuser(
            email="admin@hospital.lk",
            password="adminpassword123",
        )
        self.assertEqual(admin_user.email, "admin@hospital.lk")
        self.assertTrue(admin_user.is_staff)
        self.assertTrue(admin_user.is_superuser)

    def test_create_superuser_invalid_flags_raises_error(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="admin1@hospital.lk", password="pass", is_staff=False)
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="admin2@hospital.lk", password="pass", is_superuser=False)


class UserModelTests(TestCase):
    """Tests for User model methods and helper properties."""

    def test_user_str_with_full_name(self):
        user = User.objects.create_user(
            email="doctor@hospital.lk",
            password="pass",
            first_name="Nimal",
            last_name="Fernando",
        )
        self.assertEqual(str(user), "Nimal Fernando (doctor@hospital.lk)")

    def test_user_str_without_full_name(self):
        user = User.objects.create_user(email="staff@hospital.lk", password="pass")
        self.assertEqual(str(user), "staff@hospital.lk")

    def test_is_doctor_property(self):
        doctor = User.objects.create_user(email="doc@hospital.lk", password="pass", role=User.Role.DOCTOR)
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)
        self.assertTrue(doctor.is_doctor)
        self.assertFalse(nurse.is_doctor)

    def test_is_nurse_property(self):
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)
        doctor = User.objects.create_user(email="doc@hospital.lk", password="pass", role=User.Role.DOCTOR)
        self.assertTrue(nurse.is_nurse)
        self.assertFalse(doctor.is_nurse)

    def test_is_data_entry_property(self):
        de = User.objects.create_user(email="de@hospital.lk", password="pass", role=User.Role.DATA_ENTRY)
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)
        self.assertTrue(de.is_data_entry)
        self.assertFalse(nurse.is_data_entry)

    def test_is_unit_admin_property(self):
        unit_admin = User.objects.create_user(
            email="uadmin@hospital.lk", password="pass", role=User.Role.UNIT_ADMIN
        )
        sys_admin = User.objects.create_user(
            email="sadmin@hospital.lk", password="pass", role=User.Role.SYSTEM_ADMIN
        )
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)

        self.assertTrue(unit_admin.is_unit_admin)
        self.assertTrue(sys_admin.is_unit_admin)
        self.assertFalse(nurse.is_unit_admin)

    def test_is_system_admin_property(self):
        sys_admin = User.objects.create_user(email="sadmin@hospital.lk", password="pass", role=User.Role.SYSTEM_ADMIN)
        super_user = User.objects.create_superuser(email="super@hospital.lk", password="pass")
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)

        self.assertTrue(sys_admin.is_system_admin)
        self.assertTrue(super_user.is_system_admin)
        self.assertFalse(nurse.is_system_admin)

    def test_is_clinical_staff_property(self):
        doctor = User.objects.create_user(email="doc@hospital.lk", password="pass", role=User.Role.DOCTOR)
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)
        unit_admin = User.objects.create_user(email="uadmin@hospital.lk", password="pass", role=User.Role.UNIT_ADMIN)
        sys_admin = User.objects.create_user(email="sadmin@hospital.lk", password="pass", role=User.Role.SYSTEM_ADMIN)
        data_entry = User.objects.create_user(email="de@hospital.lk", password="pass", role=User.Role.DATA_ENTRY)

        self.assertTrue(doctor.is_clinical_staff)
        self.assertTrue(nurse.is_clinical_staff)
        self.assertTrue(unit_admin.is_clinical_staff)
        self.assertTrue(sys_admin.is_clinical_staff)
        self.assertFalse(data_entry.is_clinical_staff)

    def test_can_prescribe_property(self):
        doctor = User.objects.create_user(email="doc@hospital.lk", password="pass", role=User.Role.DOCTOR)
        sys_admin = User.objects.create_user(email="sadmin@hospital.lk", password="pass", role=User.Role.SYSTEM_ADMIN)
        nurse = User.objects.create_user(email="nurse@hospital.lk", password="pass", role=User.Role.NURSE)

        self.assertTrue(doctor.can_prescribe)
        self.assertTrue(sys_admin.can_prescribe)
        self.assertFalse(nurse.can_prescribe)

    def test_user_primary_unit_association(self):
        unit = ThalassemiaUnit.objects.create(name="Colombo North Hospital Unit")
        user = User.objects.create_user(email="unit_nurse@hospital.lk", password="pass", primary_unit=unit)
        self.assertEqual(user.primary_unit, unit)
        self.assertIn(user, unit.staff_members.all())

    def test_user_preferences_json_field(self):
        user = User.objects.create_user(
            email="pref_test@hospital.lk",
            password="pass",
            preferences={"notifications_enabled": True, "items_per_page": 25},
        )
        self.assertEqual(user.preferences["notifications_enabled"], True)
        self.assertEqual(user.preferences["items_per_page"], 25)


class AuthenticationViewsTests(TestCase):
    """Tests for Login and Logout views."""

    def setUp(self):
        self.password = "password123"
        self.user = User.objects.create_user(email="testuser@hospital.lk", password=self.password)

    def test_login_page_get(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "users/login.html")

    def test_login_success(self):
        response = self.client.post(
            reverse("login"),
            {"username": "testuser@hospital.lk", "password": self.password},
            follow=True,
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(response.context["user"].is_authenticated)

    def test_login_failure_invalid_credentials(self):
        response = self.client.post(
            reverse("login"),
            {"username": "testuser@hospital.lk", "password": "wrongpassword"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_login_inactive_user_fails(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("login"),
            {"username": "testuser@hospital.lk", "password": self.password},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["form"].is_valid())

    def test_redirect_authenticated_user_from_login_page(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("dashboard"))

    def test_logout_view(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))


class DashboardViewTests(TestCase):
    """Tests for the main dashboard view."""

    def setUp(self):
        from clients.models import ClientCareUnit

        self.unit = ThalassemiaUnit.objects.create(name="National Thalassemia Center")
        self.user = User.objects.create_user(email="user@hospital.lk", password="pass", primary_unit=self.unit)
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-001",
            full_name="Dashboard Patient",
            gender="M",
            date_of_birth="2010-01-01",
        )
        ClientCareUnit.objects.create(client=self.client_obj, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        self.admission = Admission.objects.create(
            client=self.client_obj,
            date_of_admission="2026-03-01",
        )
        self.transfusion = Transfusion.objects.create(
            admission=self.admission,
            date_of_transfusion="2026-03-01",
            pre_HB_level=9.0,
            post_HB_level=11.5,
            amount_of_blood=300,
        )

    def test_dashboard_access_unauthenticated_redirects(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_dashboard_access_authenticated_success(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "dashboard.html")

        # Verify context metrics
        self.assertEqual(response.context["total_clients"], 1)
        self.assertEqual(response.context["total_admissions"], 1)
        self.assertEqual(response.context["total_transfusions"], 1)
        self.assertEqual(response.context["total_units"], 1)

    def test_dashboard_metrics_scoped_by_user_unit(self):
        from clients.models import ClientCareUnit, ThalassemiaUnit

        unit_b = ThalassemiaUnit.objects.create(name="Second Unit")
        nurse_b = User.objects.create_user(email="nurse_b@hospital.lk", password="pass", role=User.Role.NURSE, primary_unit=unit_b)

        # Nurse B has 0 clients in Unit B
        self.client.force_login(nurse_b)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_clients"], 0)
        self.assertEqual(response.context["total_admissions"], 0)

        # System Admin sees global metrics (1 client)
        sys_admin = User.objects.create_user(email="admin@hospital.lk", password="pass", role=User.Role.SYSTEM_ADMIN)
        self.client.force_login(sys_admin)
        response_admin = self.client.get(reverse("dashboard"))
        self.assertEqual(response_admin.status_code, 200)
        self.assertEqual(response_admin.context["total_clients"], 1)


class UpdatePreferencesViewTests(TestCase):
    """Tests for user preference updates (Theme toggle and Dark Mode)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="pref_user@hospital.lk",
            password="pass",
            color_scheme="light",
            dark_mode=False,
        )

    def test_update_preferences_get_method_not_allowed(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("update_preferences"))
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

    def test_update_preferences_unauthenticated_redirects(self):
        response = self.client.post(reverse("update_preferences"), {"color_scheme": "dark"})
        self.assertEqual(response.status_code, 302)

    def test_update_color_scheme_to_dark(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("update_preferences"), {"color_scheme": "dark"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["color_scheme"], "dark")
        self.assertTrue(data["dark_mode"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.color_scheme, "dark")
        self.assertTrue(self.user.dark_mode)

    def test_update_color_scheme_to_light(self):
        self.user.color_scheme = "dark"
        self.user.dark_mode = True
        self.user.save()

        self.client.force_login(self.user)
        response = self.client.post(reverse("update_preferences"), {"color_scheme": "light"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["color_scheme"], "light")
        self.assertFalse(data["dark_mode"])

        self.user.refresh_from_db()
        self.assertEqual(self.user.color_scheme, "light")
        self.assertFalse(self.user.dark_mode)

    def test_update_dark_mode_boolean(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("update_preferences"), {"dark_mode": "true"})
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.dark_mode)
        self.assertEqual(self.user.color_scheme, "dark")

    def test_update_preferences_invalid_scheme(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("update_preferences"), {"color_scheme": "invalid_theme"})
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["status"], "no_change")

        self.user.refresh_from_db()
        self.assertEqual(self.user.color_scheme, "light")
        self.assertFalse(self.user.dark_mode)


class PermissionsModuleTests(TestCase):
    """Tests for users/permissions.py mixins and helpers."""

    def setUp(self):
        self.doctor = User.objects.create_user(email="doc_perm@hospital.lk", password="pass", role=User.Role.DOCTOR)
        self.nurse = User.objects.create_user(email="nurse_perm@hospital.lk", password="pass", role=User.Role.NURSE)
        self.data_entry = User.objects.create_user(email="de_perm@hospital.lk", password="pass", role=User.Role.DATA_ENTRY)
        self.unit_admin = User.objects.create_user(email="uadmin_perm@hospital.lk", password="pass", role=User.Role.UNIT_ADMIN)

        self.client_obj = Client.objects.create(
            registration_number="TH-PERM-001",
            full_name="Permission Test Patient",
            gender="F",
            date_of_birth="2015-05-05",
        )
        self.admission = Admission.objects.create(
            client=self.client_obj,
            date_of_admission="2026-01-01",
        )

    def test_can_user_edit_entry_for_elevated_roles(self):
        from users.permissions import can_user_edit_entry
        self.assertTrue(can_user_edit_entry(self.doctor, self.admission))
        self.assertTrue(can_user_edit_entry(self.unit_admin, self.admission))

    def test_can_user_edit_entry_time_window_recent(self):
        from users.permissions import can_user_edit_entry
        from django.utils import timezone

        # Entry created right now with recent date of admission
        self.admission.date_of_admission = timezone.localdate()
        self.admission.created_at = timezone.now()
        self.admission.save()

        self.assertTrue(can_user_edit_entry(self.data_entry, self.admission, window_hours=48))
        self.assertTrue(can_user_edit_entry(self.nurse, self.admission, window_hours=48))

    def test_can_user_edit_entry_time_window_expired(self):
        from users.permissions import can_user_edit_entry
        from django.utils import timezone
        import datetime

        # Entry created 72 hours ago
        old_time = timezone.now() - datetime.timedelta(hours=72)
        Admission.objects.filter(pk=self.admission.pk).update(created_at=old_time)
        self.admission.refresh_from_db()

        # Data Entry & Nurse cannot edit expired entry
        self.assertFalse(can_user_edit_entry(self.data_entry, self.admission, window_hours=48))
        self.assertFalse(can_user_edit_entry(self.nurse, self.admission, window_hours=48))

        # Doctor & Unit Admin can still edit expired entry
        self.assertTrue(can_user_edit_entry(self.doctor, self.admission, window_hours=48))
        self.assertTrue(can_user_edit_entry(self.unit_admin, self.admission, window_hours=48))

