import datetime
from io import BytesIO
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clients.models import Admission, Choice, Client, Investigation, InvestigationType, Laboratory, Transfusion

User = get_user_model()


class ClientPhotoOptimizationTests(TestCase):
    def test_client_photo_auto_crop_and_resize(self):
        # Generate a large 1200x800 RGB test image
        img = Image.new("RGB", (1200, 800), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        uploaded = SimpleUploadedFile("large_photo.jpg", buffer.getvalue(), content_type="image/jpeg")

        client = Client.objects.create(
            registration_number="TH-2026-888",
            full_name="Photo Test Patient",
            gender="F",
            date_of_birth="2018-01-01",
            photo=uploaded,
        )

        # Open saved photo and verify dimensions are cropped & resized to 400x400
        saved_img = Image.open(client.photo.path)
        self.assertEqual(saved_img.size, (400, 400))


class AdmissionTransfusionWorkflowTests(TestCase):
    def setUp(self):
        from clients.models import ClientCareUnit, ThalassemiaUnit

        self.unit = ThalassemiaUnit.objects.create(name="Admission Unit")
        self.user = User.objects.create_user(email="doctor@hospital.lk", password="pass123", primary_unit=self.unit)
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-999",
            full_name="Test Thalassemia Patient",
            gender="M",
            date_of_birth="2015-05-10",
        )
        ClientCareUnit.objects.create(client=self.client_obj, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        self.reason_choice = Choice.objects.create(
            category="admission_reason",
            name="Blood Transfusion",
        )

    def test_admission_and_transfusion_creation(self):
        self.client.force_login(self.user)

        now = timezone.localtime()
        adm_time = (now - datetime.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M")
        tr_time = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")

        # 1. Create Admission via HTMX POST
        create_adm_url = reverse("clients:admission-create", kwargs={"client_id": self.client_obj.pk})
        resp = self.client.post(
            create_adm_url,
            {
                "date_of_admission": adm_time,
                "reason_for_admission": self.reason_choice.pk,
                "notes": "Routine transfusion admission",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("HX-Trigger"), "reloadAdmissions")
        self.assertEqual(Admission.objects.count(), 1)

        admission = Admission.objects.first()
        self.assertEqual(admission.client, self.client_obj)

        # 2. Log Transfusion under Admission via HTMX POST
        create_tr_url = reverse("clients:transfusion-create", kwargs={"admission_id": admission.pk})
        resp_tr = self.client.post(
            create_tr_url,
            {
                "date_of_transfusion": tr_time,
                "pre_HB_level": "8.5",
                "post_HB_level": "11.2",
                "amount_of_blood": "350",
                "reaction": "None",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp_tr.status_code, 200)
        self.assertEqual(resp_tr.headers.get("HX-Trigger"), "reloadAdmissions")
        self.assertEqual(Transfusion.objects.count(), 1)

        transfusion = Transfusion.objects.first()
        self.assertEqual(transfusion.admission, admission)
        self.assertEqual(float(transfusion.pre_HB_level), 8.5)

    def test_transfusion_timing_validation(self):
        from django.core.exceptions import ValidationError

        now = timezone.now()
        adm = Admission.objects.create(
            client=self.client_obj,
            date_of_admission=now - datetime.timedelta(hours=4),
            date_of_discharge=now - datetime.timedelta(hours=1),
        )

        # 1. Transfusion earlier than admission should fail
        tr_early = Transfusion(
            admission=adm,
            date_of_transfusion=now - datetime.timedelta(hours=5),
        )
        with self.assertRaises(ValidationError):
            tr_early.full_clean()

        # 2. Transfusion later than discharge should fail
        tr_late = Transfusion(
            admission=adm,
            date_of_transfusion=now,
        )
        with self.assertRaises(ValidationError):
            tr_late.full_clean()

        # 3. Transfusion within admission window succeeds
        tr_valid = Transfusion(
            admission=adm,
            date_of_transfusion=now - datetime.timedelta(hours=2),
        )
        tr_valid.full_clean()  # should not raise

    def test_routine_day_transfusion_auto_discharges(self):
        self.client.force_login(self.user)
        now = timezone.localtime()

        # Create day-care admission
        adm = Admission.objects.create(
            client=self.client_obj,
            date_of_admission=now - datetime.timedelta(hours=3),
            is_routine_day_transfusion=True,
            reason_for_admission=self.reason_choice,
        )
        self.assertIsNone(adm.date_of_discharge)

        # Log transfusion under this day-care admission
        create_tr_url = reverse("clients:transfusion-create", kwargs={"admission_id": adm.pk})
        tr_time = (now - datetime.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
        resp = self.client.post(
            create_tr_url,
            {
                "date_of_transfusion": tr_time,
                "amount_of_blood": "250",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)

        # Admission should now be auto-discharged!
        adm.refresh_from_db()
        self.assertIsNotNone(adm.date_of_discharge)
        self.assertIn("Routine Day-Care", adm.outcome)

    def test_close_previous_admission_strategy(self):
        self.client.force_login(self.user)
        now = timezone.localtime()

        # Existing unclosed admission from 5 days ago
        old_adm = Admission.objects.create(
            client=self.client_obj,
            date_of_admission=now - datetime.timedelta(days=5),
            reason_for_admission=self.reason_choice,
        )
        self.assertIsNone(old_adm.date_of_discharge)

        # Create new admission with close_previous_admission=true
        create_adm_url = reverse("clients:admission-create", kwargs={"client_id": self.client_obj.pk})
        new_adm_time = now.strftime("%Y-%m-%dT%H:%M")
        resp = self.client.post(
            create_adm_url,
            {
                "date_of_admission": new_adm_time,
                "reason_for_admission": self.reason_choice.pk,
                "close_previous_admission": "true",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)

        old_adm.refresh_from_db()
        self.assertIsNotNone(old_adm.date_of_discharge)
        self.assertIn("Closed upon new admission", old_adm.outcome)

    def test_quick_discharge_endpoint(self):
        self.client.force_login(self.user)
        now = timezone.now()

        adm = Admission.objects.create(
            client=self.client_obj,
            date_of_admission=now - datetime.timedelta(hours=2),
            reason_for_admission=self.reason_choice,
        )
        self.assertIsNone(adm.date_of_discharge)

        discharge_url = reverse("clients:admission-discharge", kwargs={"pk": adm.pk})
        resp = self.client.post(discharge_url, HTTP_HX_REQUEST="true")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("HX-Trigger"), "reloadAdmissions")

        adm.refresh_from_db()
        self.assertIsNotNone(adm.date_of_discharge)
        self.assertEqual(adm.outcome, "Discharged via Quick-Action")


class InvestigationWorkflowTests(TestCase):
    def setUp(self):
        from clients.models import ClientCareUnit, ThalassemiaUnit

        self.unit = ThalassemiaUnit.objects.create(name="Reference Unit")
        self.user = User.objects.create_user(email="doctor@hospital.lk", password="pass123", primary_unit=self.unit)
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-777",
            full_name="Investigation Test Patient",
            gender="F",
            date_of_birth="2016-08-15",
        )
        ClientCareUnit.objects.create(client=self.client_obj, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        self.inv_type = InvestigationType.objects.create(
            name="Serum Ferritin",
            unit="ng/mL",
            reference_range="30 - 300",
        )
        self.laboratory = Laboratory.objects.create(
            name="National Thalassemia Reference Lab",
            code="NTRL",
        )

    def test_investigation_create_and_update(self):
        self.client.force_login(self.user)

        # 1. Create Investigation via HTMX POST
        create_url = reverse("clients:investigation-create", kwargs={"client_id": self.client_obj.pk})
        resp = self.client.post(
            create_url,
            {
                "investigation_type": self.inv_type.pk,
                "date_done": timezone.localdate(),
                "value": "2450.50",
                "laboratory": self.laboratory.pk,
                "notes": "High serum ferritin level observed",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("HX-Trigger"), "reloadInvestigations")
        self.assertEqual(Investigation.objects.count(), 1)

        inv = Investigation.objects.first()
        self.assertEqual(inv.client, self.client_obj)
        self.assertEqual(inv.investigation_type, self.inv_type)
        self.assertEqual(inv.value, 2450.50)
        self.assertEqual(inv.laboratory, self.laboratory)

        # 2. Update Investigation via HTMX POST
        update_url = reverse("clients:investigation-update", kwargs={"pk": inv.pk})
        resp_update = self.client.post(
            update_url,
            {
                "investigation_type": self.inv_type.pk,
                "date_done": timezone.localdate(),
                "value": "2100.00",
                "laboratory": self.laboratory.pk,
                "notes": "Re-evaluated after chelation dosage increase",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(resp_update.status_code, 200)
        self.assertEqual(resp_update.headers.get("HX-Trigger"), "reloadInvestigations")

        inv.refresh_from_db()
        self.assertEqual(inv.value, 2100.00)
        self.assertEqual(inv.notes, "Re-evaluated after chelation dosage increase")

        # 3. Test Partial View Rendering
        partial_url = reverse("clients:investigations-partial", kwargs={"client_id": self.client_obj.pk})
        resp_partial = self.client.get(partial_url)
        self.assertEqual(resp_partial.status_code, 200)
        self.assertContains(resp_partial, "Serum Ferritin")
        self.assertContains(resp_partial, "National Thalassemia Reference Lab")

    def test_latest_investigations_in_client_detail_context(self):
        self.client.force_login(self.user)

        # Create two tests for the same investigation type on different dates
        Investigation.objects.create(
            client=self.client_obj,
            investigation_type=self.inv_type,
            date_done="2026-01-01",
            value=3200.0,
            laboratory=self.laboratory,
        )
        inv_new = Investigation.objects.create(
            client=self.client_obj,
            investigation_type=self.inv_type,
            date_done="2026-03-01",
            value=2100.0,
            laboratory=self.laboratory,
        )

        detail_url = reverse("clients:client-detail", kwargs={"pk": self.client_obj.pk})
        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("latest_investigations", response.context)
        latest_list = response.context["latest_investigations"]
        self.assertEqual(len(latest_list), 1)
        self.assertEqual(latest_list[0].pk, inv_new.pk)
        self.assertEqual(latest_list[0].value, 2100.0)

    def test_periodic_investigation_surveillance_alerts(self):
        self.client.force_login(self.user)

        # Set recommended interval to 3 months for Ferritin
        self.inv_type.recommended_interval_months = 3
        self.inv_type.save()

        # Create an old test done 6 months ago (so it is overdue)
        six_months_ago = (timezone.localdate() - timezone.timedelta(days=180)).strftime("%Y-%m-%d")
        inv_overdue = Investigation.objects.create(
            client=self.client_obj,
            investigation_type=self.inv_type,
            date_done=six_months_ago,
            value=3500.0,
            laboratory=self.laboratory,
        )

        detail_url = reverse("clients:client-detail", kwargs={"pk": self.client_obj.pk})
        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertIn("overdue_investigations", response.context)
        overdue_list = response.context["overdue_investigations"]
        self.assertEqual(len(overdue_list), 1)
        self.assertEqual(overdue_list[0].pk, inv_overdue.pk)
        self.assertTrue(inv_overdue.surveillance_status["is_overdue"])
        self.assertContains(response, "Periodic Surveillance Tests Overdue")


class UnitScopedClientPermissionsTests(TestCase):
    """Tests for unit-scoped authorization rules on Client views."""

    def setUp(self):
        from clients.models import ClientCareUnit, ThalassemiaUnit

        self.unit_a = ThalassemiaUnit.objects.create(name="Ragama Thalassemia Unit")
        self.unit_b = ThalassemiaUnit.objects.create(name="Kurunegala Thalassemia Center")

        self.nurse_a = User.objects.create_user(
            email="nurse_a@ragama.lk", password="pass", role=User.Role.NURSE, primary_unit=self.unit_a
        )
        self.nurse_b = User.objects.create_user(
            email="nurse_b@kurunegala.lk", password="pass", role=User.Role.NURSE, primary_unit=self.unit_b
        )
        self.sys_admin = User.objects.create_user(
            email="admin@health.lk", password="pass", role=User.Role.SYSTEM_ADMIN
        )

        self.client_a = Client.objects.create(
            registration_number="TH-RAG-001",
            full_name="Ragama Patient",
            gender="M",
            date_of_birth="2012-01-01",
        )
        ClientCareUnit.objects.create(
            client=self.client_a, unit=self.unit_a, role=ClientCareUnit.Role.PRIMARY, is_active=True
        )

        self.client_b = Client.objects.create(
            registration_number="TH-KUR-001",
            full_name="Kurunegala Patient",
            gender="F",
            date_of_birth="2014-06-01",
        )
        ClientCareUnit.objects.create(
            client=self.client_b, unit=self.unit_b, role=ClientCareUnit.Role.PRIMARY, is_active=True
        )

    def test_unit_staff_directory_list_filtering(self):
        # Nurse A should only see Ragama patient
        self.client.force_login(self.nurse_a)
        response = self.client.get(reverse("clients:client-list"))
        self.assertEqual(response.status_code, 200)
        client_list = response.context["clients"]
        self.assertIn(self.client_a, client_list)
        self.assertNotIn(self.client_b, client_list)

    def test_unit_staff_cross_unit_access_forbidden(self):
        # Nurse A attempting to access Nurse B's patient receives 403 or 404 (Access Blocked)
        self.client.force_login(self.nurse_a)
        
        detail_url_b = reverse("clients:client-detail", kwargs={"pk": self.client_b.pk})
        response_b = self.client.get(detail_url_b)
        self.assertIn(response_b.status_code, [403, 404])

        edit_url_b = reverse("clients:client-update", kwargs={"pk": self.client_b.pk})
        response_edit_b = self.client.get(edit_url_b)
        self.assertIn(response_edit_b.status_code, [403, 404])

        # Nurse A accessing own patient receives 200 OK
        detail_url_a = reverse("clients:client-detail", kwargs={"pk": self.client_a.pk})
        response_a = self.client.get(detail_url_a)
        self.assertEqual(response_a.status_code, 200)

    def test_client_registration_auto_assigns_user_primary_unit(self):
        from clients.models import ClientCareUnit

        self.client.force_login(self.nurse_a)
        create_url = reverse("clients:client-create")
        response = self.client.post(
            create_url,
            {
                "registration_number": "TH-RAG-002",
                "full_name": "New Ragama Child",
                "gender": "M",
                "date_of_birth": "2020-03-15",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        
        new_client = Client.objects.get(registration_number="TH-RAG-002")
        self.assertEqual(new_client.primary_care_unit, self.unit_a)

    def test_system_admin_unrestricted_access(self):
        self.client.force_login(self.sys_admin)

        # System admin sees all clients in directory
        response = self.client.get(reverse("clients:client-list"))
        self.assertEqual(response.status_code, 200)
        client_list = response.context["clients"]
        self.assertIn(self.client_a, client_list)
        self.assertIn(self.client_b, client_list)

        # System admin can access detail & edit pages for any unit's patient
        response_a = self.client.get(reverse("clients:client-detail", kwargs={"pk": self.client_a.pk}))
        response_b = self.client.get(reverse("clients:client-detail", kwargs={"pk": self.client_b.pk}))
        self.assertEqual(response_a.status_code, 200)
        self.assertEqual(response_b.status_code, 200)

    def test_htmx_permission_denied_returns_modal(self):
        # Create an admission older than 48 hours
        old_admission = Admission.objects.create(
            client=self.client_a,
            date_of_admission=timezone.now() - datetime.timedelta(days=5),
        )
        Admission.objects.filter(pk=old_admission.pk).update(
            created_at=timezone.now() - datetime.timedelta(hours=120)
        )
        self.client.force_login(self.nurse_a)

        # Non-HTMX GET returns 403 PermissionDenied
        edit_url = reverse("clients:admission-update", kwargs={"pk": old_admission.pk})
        resp = self.client.get(edit_url)
        self.assertEqual(resp.status_code, 403)

        # HTMX GET returns 200 with permission denied modal partial
        htmx_resp = self.client.get(edit_url, HTTP_HX_REQUEST="true")
        self.assertEqual(htmx_resp.status_code, 200)
        self.assertTemplateUsed(htmx_resp, "clients/modals/permission_denied_modal.html")
        self.assertContains(htmx_resp, "Editing Restricted")

    def test_historical_transfusion_event_date_locked(self):
        from users.permissions import can_user_edit_entry
        import datetime

        # Create admission and a historical transfusion with timezone-aware datetime
        adm_dt = timezone.make_aware(datetime.datetime(2026, 1, 1, 9, 0))
        tr_dt = timezone.make_aware(datetime.datetime(2026, 1, 1, 11, 0))
        admission = Admission.objects.create(
            client=self.client_a,
            date_of_admission=adm_dt,
        )
        transfusion = Transfusion.objects.create(
            admission=admission,
            date_of_transfusion=tr_dt,
        )

        # Nurse A cannot edit historical transfusion even if created_at is today
        self.assertFalse(can_user_edit_entry(self.nurse_a, transfusion))

        # System Admin can edit historical transfusion
        self.assertTrue(can_user_edit_entry(self.sys_admin, transfusion))



