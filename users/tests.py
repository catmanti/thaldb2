from django.contrib.auth import get_user_model
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
        self.user = User.objects.create_user(email="user@hospital.lk", password="pass")
        self.unit = ThalassemiaUnit.objects.create(name="National Thalassemia Center")
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-001",
            full_name="Dashboard Patient",
            gender="M",
            date_of_birth="2010-01-01",
        )
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


class UpdatePreferencesViewTests(TestCase):
    """Tests for user preference updates (Theme toggle and Dark Mode)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="pref_user@hospital.lk",
            password="pass",
            color_scheme="light",
            dark_mode=False,
        )

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
