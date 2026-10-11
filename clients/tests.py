import datetime
from io import BytesIO
from PIL import Image
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from clients.models import (
    Admission,
    Choice,
    Client,
    ClientCareAssignment,
    ClientCareUnit,
    DoctorCoverage,
    Investigation,
    InvestigationType,
    Laboratory,
    ThalassemiaUnit,
    Transfusion,
)

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


class ClientBMTTests(TestCase):
    def setUp(self):
        from clients.models import ClientCareUnit, ThalassemiaUnit

        self.unit = ThalassemiaUnit.objects.create(name="Colombo Unit")
        self.user = User.objects.create_user(email="doctor@colombo.lk", password="pass", primary_unit=self.unit)
        self.client_obj = Client.objects.create(
            registration_number="TH-BMT-001",
            full_name="BMT Test Patient",
            gender="M",
            date_of_birth="2016-01-01",
            diagnosis_details="IVS1-5 G>C homozygous",
        )
        ClientCareUnit.objects.create(
            client=self.client_obj, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True
        )

    def test_client_bmt_and_has_bmt_property(self):
        from clients.models import ClientBMT

        # Initially client has no BMT
        self.assertFalse(self.client_obj.has_bmt)
        self.assertEqual(self.client_obj.bmt_records.count(), 0)

        # Create first BMT record
        bmt1 = ClientBMT.objects.create(
            client=self.client_obj,
            date_of_bmt="2024-05-10",
            institution_name="Christian Medical College, Vellore",
            donor_type="Matched Sibling (MSD)",
            is_successful=True,
            notes="Full donor chimerism achieved",
        )

        self.assertTrue(self.client_obj.has_bmt)
        self.assertEqual(self.client_obj.bmt_records.count(), 1)
        self.assertEqual(str(bmt1), f"BMT on 2024-05-10 - {self.client_obj.full_name}")

        # Support multiple BMTs
        bmt2 = ClientBMT.objects.create(
            client=self.client_obj,
            date_of_bmt="2025-06-15",
            institution_name="Asiri Central Hospital",
            donor_type="Haploidentical",
            is_successful=True,
        )

        self.assertEqual(self.client_obj.bmt_records.count(), 2)
        # Verify ordering is -date_of_bmt
        records = list(self.client_obj.bmt_records.all())
        self.assertEqual(records[0], bmt2)
        self.assertEqual(records[1], bmt1)

    def test_client_detail_renders_bmt_and_diagnosis_details(self):
        from clients.models import ClientBMT

        ClientBMT.objects.create(
            client=self.client_obj,
            date_of_bmt="2024-05-10",
            institution_name="CMC Vellore",
            donor_type="Matched Sibling",
            is_successful=True,
        )

        self.client.force_login(self.user)
        detail_url = reverse("clients:client-detail", kwargs={"pk": self.client_obj.pk})
        response = self.client.get(detail_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "IVS1-5 G&gt;C homozygous")
        self.assertContains(response, "CMC Vellore")
        self.assertContains(response, "Matched Sibling")
        self.assertContains(response, "BMT Done")


class DeceasedAndBMTRegistryTests(TestCase):
    def setUp(self):
        from clients.models import ClientBMT, ClientCareUnit, ClientDeath, ThalassemiaUnit

        self.unit_a = ThalassemiaUnit.objects.create(name="Kurunegala TH")
        self.unit_b = ThalassemiaUnit.objects.create(name="Ragama TH")

        self.nurse_a = User.objects.create_user(
            email="nurse_kuru@test.lk", password="pass", role=User.Role.NURSE, primary_unit=self.unit_a
        )
        self.admin_user = User.objects.create_user(
            email="admin_health@test.lk", password="pass", role=User.Role.SYSTEM_ADMIN
        )

        # 1. Active Client in Kurunegala
        self.active_client = Client.objects.create(
            registration_number="TH-ACT-001", full_name="Active Patient", gender="M", date_of_birth="2015-01-01"
        )
        ClientCareUnit.objects.create(
            client=self.active_client, unit=self.unit_a, role=ClientCareUnit.Role.PRIMARY, is_active=True
        )

        # 2. Deceased Client in Kurunegala
        self.dead_client_a = Client.objects.create(
            registration_number="TH-DEC-001", full_name="Deceased Patient Kurunegala", gender="M", date_of_birth="1990-01-01"
        )
        ClientDeath.objects.create(
            client=self.dead_client_a, date_of_death="2020-05-15", cause_of_death="Heart Failure"
        )
        ClientCareUnit.objects.create(
            client=self.dead_client_a, unit=self.unit_a, role=ClientCareUnit.Role.PRIMARY, is_active=False, start_date="2010-01-01", end_date="2020-05-15"
        )

        # 3. Deceased Client in Ragama
        self.dead_client_b = Client.objects.create(
            registration_number="TH-DEC-002", full_name="Deceased Patient Ragama", gender="F", date_of_birth="1992-01-01"
        )
        ClientDeath.objects.create(
            client=self.dead_client_b, date_of_death="2021-08-20", cause_of_death="Sepsis"
        )
        ClientCareUnit.objects.create(
            client=self.dead_client_b, unit=self.unit_b, role=ClientCareUnit.Role.PRIMARY, is_active=False, start_date="2012-01-01", end_date="2021-08-20"
        )

        # 4. BMT Client in Kurunegala
        self.bmt_client = Client.objects.create(
            registration_number="TH-BMT-002", full_name="Post BMT Patient", gender="M", date_of_birth="2010-06-01"
        )
        ClientBMT.objects.create(
            client=self.bmt_client, date_of_bmt="2023-01-10", institution_name="CMC Vellore", is_successful=True
        )
        ClientCareUnit.objects.create(
            client=self.bmt_client, unit=self.unit_a, role=ClientCareUnit.Role.PRIMARY, is_active=False, start_date="2015-01-01", end_date="2023-01-10"
        )

    def test_primary_care_unit_fallback_for_inactive_clients(self):
        # Even though care link is inactive, primary_care_unit resolves to Kurunegala TH
        self.assertEqual(self.dead_client_a.primary_care_unit, self.unit_a)
        self.assertFalse(self.dead_client_a.is_active_care)

        self.assertEqual(self.bmt_client.primary_care_unit, self.unit_a)
        self.assertFalse(self.bmt_client.is_active_care)

    def test_active_directory_excludes_inactive_and_deceased_and_bmt(self):
        self.client.force_login(self.nurse_a)
        response = self.client.get(reverse("clients:client-list"))
        self.assertEqual(response.status_code, 200)
        clients = response.context["clients"]
        self.assertIn(self.active_client, clients)
        self.assertNotIn(self.dead_client_a, clients)
        self.assertNotIn(self.bmt_client, clients)

    def test_deceased_registry_unit_scoping(self):
        # Nurse A should only see deceased client in Kurunegala
        self.client.force_login(self.nurse_a)
        response = self.client.get(reverse("clients:client-deceased-list"))
        self.assertEqual(response.status_code, 200)
        clients = response.context["clients"]
        self.assertIn(self.dead_client_a, clients)
        self.assertNotIn(self.dead_client_b, clients)
        self.assertNotIn(self.active_client, clients)

        # Admin sees both deceased clients
        self.client.force_login(self.admin_user)
        resp_admin = self.client.get(reverse("clients:client-deceased-list"))
        self.assertEqual(resp_admin.status_code, 200)
        admin_clients = resp_admin.context["clients"]
        self.assertIn(self.dead_client_a, admin_clients)
        self.assertIn(self.dead_client_b, admin_clients)

    def test_bmt_registry_listing(self):
        self.client.force_login(self.nurse_a)
        response = self.client.get(reverse("clients:client-bmt-list"))
        self.assertEqual(response.status_code, 200)
        clients = response.context["clients"]
        self.assertIn(self.bmt_client, clients)
        self.assertNotIn(self.active_client, clients)
        self.assertNotIn(self.dead_client_a, clients)

    def test_detail_view_accessible_for_inactive_unit_client(self):
        # Nurse A can view profile of deceased patient from Kurunegala
        self.client.force_login(self.nurse_a)
        resp = self.client.get(reverse("clients:client-detail", kwargs={"pk": self.dead_client_a.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Deceased")
        self.assertContains(resp, "Kurunegala TH")


class ClientCareAssignmentTests(TestCase):
    def setUp(self):
        from django.core.exceptions import ValidationError

        self.ValidationError = ValidationError
        self.unit = ThalassemiaUnit.objects.create(name="Kurunegala Centre")
        self.doc_a = User.objects.create_user(
            email="dr.a@hospital.lk",
            password="pass",
            first_name="Sunil",
            last_name="Perera",
            role=User.Role.DOCTOR,
            primary_unit=self.unit,
        )
        self.doc_b = User.objects.create_user(
            email="dr.b@hospital.lk",
            password="pass",
            first_name="Kamal",
            last_name="Silva",
            role=User.Role.DOCTOR,
            primary_unit=self.unit,
        )
        self.doc_cover = User.objects.create_user(
            email="dr.cover@hospital.lk",
            password="pass",
            first_name="Anura",
            last_name="Fernando",
            role=User.Role.DOCTOR,
            primary_unit=self.unit,
        )
        self.admin_user = User.objects.create_user(
            email="admin@hospital.lk",
            password="pass",
            role=User.Role.UNIT_ADMIN,
            primary_unit=self.unit,
        )

        self.client_patient = Client.objects.create(
            registration_number="TH-TEST-DOC-01",
            full_name="Male Patient Test",
            gender="M",
            date_of_birth="2010-05-15",
        )
        ClientCareUnit.objects.create(
            client=self.client_patient,
            unit=self.unit,
            role=ClientCareUnit.Role.PRIMARY,
            is_active=True,
        )

    def test_client_doctor_assignment_lifecycle(self):
        # 1. Assign Doctor A
        assign1 = ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=datetime.date(2025, 1, 1),
            assigned_by=self.admin_user,
        )
        self.assertEqual(self.client_patient.assigned_doctor, self.doc_a)
        self.assertEqual(self.client_patient.current_duty_doctor, self.doc_a)
        self.assertFalse(self.client_patient.is_doctor_on_leave)

        # 2. Close assignment 1 and assign Doctor B
        assign1.close_assignment(end_date=datetime.date(2025, 6, 30))
        assign2 = ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_b,
            valid_from=datetime.date(2025, 7, 1),
            assigned_by=self.admin_user,
        )
        self.assertEqual(self.client_patient.assigned_doctor, self.doc_b)
        self.assertEqual(self.client_patient.doctor_assignments.count(), 2)

    def test_prevent_multiple_simultaneous_active_assignments(self):
        from django.db import IntegrityError

        ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=datetime.date(2025, 1, 1),
        )

        # Attempting a second active assignment without closing the first should violate unique constraint
        with self.assertRaises(IntegrityError):
            ClientCareAssignment.objects.create(
                client=self.client_patient,
                care_unit=self.unit,
                doctor=self.doc_b,
                valid_from=datetime.date(2025, 2, 1),
            )

    def test_doctor_leave_coverage_dynamic_resolution(self):
        today = timezone.localdate()
        ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=today - datetime.timedelta(days=30),
        )

        # Before coverage
        self.assertEqual(self.client_patient.assigned_doctor, self.doc_a)
        self.assertEqual(self.client_patient.current_duty_doctor, self.doc_a)
        self.assertFalse(self.client_patient.is_doctor_on_leave)

        # Doctor A goes on leave from yesterday to next week, covered by Doc Cover
        coverage = DoctorCoverage.objects.create(
            care_unit=self.unit,
            absent_doctor=self.doc_a,
            covering_doctor=self.doc_cover,
            start_date=today - datetime.timedelta(days=2),
            end_date=today + datetime.timedelta(days=5),
            reason="Annual Leave",
            is_active=True,
        )

        # Primary doctor remains Doc A, but duty doctor dynamically points to Doc Cover
        self.assertEqual(self.client_patient.assigned_doctor, self.doc_a)
        self.assertTrue(self.client_patient.is_doctor_on_leave)
        self.assertEqual(self.client_patient.current_duty_doctor, self.doc_cover)

        # If coverage is marked inactive, falls back to Doc A
        coverage.is_active = False
        coverage.save()
        self.assertFalse(self.client_patient.is_doctor_on_leave)
        self.assertEqual(self.client_patient.current_duty_doctor, self.doc_a)

    def test_doctor_coverage_validation(self):
        today = timezone.localdate()

        # Cannot cover oneself
        cov_self = DoctorCoverage(
            care_unit=self.unit,
            absent_doctor=self.doc_a,
            covering_doctor=self.doc_a,
            start_date=today,
            end_date=today + datetime.timedelta(days=2),
        )
        with self.assertRaises(self.ValidationError):
            cov_self.clean()

        # End date cannot precede start date
        cov_date = DoctorCoverage(
            care_unit=self.unit,
            absent_doctor=self.doc_a,
            covering_doctor=self.doc_b,
            start_date=today,
            end_date=today - datetime.timedelta(days=1),
        )
        with self.assertRaises(self.ValidationError):
            cov_date.clean()

    def test_client_detail_view_renders_doctor_and_coverage(self):
        today = timezone.localdate()
        ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=today - datetime.timedelta(days=10),
        )
        DoctorCoverage.objects.create(
            care_unit=self.unit,
            absent_doctor=self.doc_a,
            covering_doctor=self.doc_cover,
            start_date=today - datetime.timedelta(days=1),
            end_date=today + datetime.timedelta(days=3),
            is_active=True,
        )

        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("clients:client-detail", kwargs={"pk": self.client_patient.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Dr. Sunil Perera")
        self.assertContains(response, "Covered")
        self.assertContains(response, "Dr. Anura Fernando")

    def test_client_directory_doctor_filtering_for_doctor(self):
        # Patient 1 assigned to Doc A
        ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=datetime.date(2025, 1, 1),
        )

        # Patient 2 assigned to Doc B
        p2 = Client.objects.create(
            registration_number="TH-TEST-DOC-02",
            full_name="Female Patient Test",
            gender="F",
            date_of_birth="2012-03-20",
        )
        ClientCareUnit.objects.create(client=p2, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)
        ClientCareAssignment.objects.create(
            client=p2,
            care_unit=self.unit,
            doctor=self.doc_b,
            valid_from=datetime.date(2025, 1, 1),
        )

        # Patient 3 is unassigned
        p3 = Client.objects.create(
            registration_number="TH-TEST-DOC-03",
            full_name="Unassigned Patient",
            gender="M",
            date_of_birth="2016-07-10",
        )
        ClientCareUnit.objects.create(client=p3, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        # 1. Doc A logs in -> default list shows only Doc A's patients
        self.client.force_login(self.doc_a)
        resp = self.client.get(reverse("clients:client-list"))
        self.assertEqual(resp.status_code, 200)
        clients_in_view = list(resp.context["clients"])
        self.assertIn(self.client_patient, clients_in_view)
        self.assertNotIn(p2, clients_in_view)
        self.assertNotIn(p3, clients_in_view)

        # 2. Doc A views "All Patients"
        resp_all = self.client.get(reverse("clients:client-list"), {"doctor": "all"})
        self.assertEqual(resp_all.status_code, 200)
        clients_all = list(resp_all.context["clients"])
        self.assertIn(self.client_patient, clients_all)
        self.assertIn(p2, clients_all)
        self.assertIn(p3, clients_all)

        # 3. Doc A views "Unassigned"
        resp_unassigned = self.client.get(reverse("clients:client-list"), {"doctor": "unassigned"})
        self.assertEqual(resp_unassigned.status_code, 200)
        clients_unassigned = list(resp_unassigned.context["clients"])
        self.assertNotIn(self.client_patient, clients_unassigned)
        self.assertNotIn(p2, clients_unassigned)
        self.assertIn(p3, clients_unassigned)

    def test_client_directory_covering_duty_filter(self):
        # Patient 1 assigned to Doc A
        ClientCareAssignment.objects.create(
            client=self.client_patient,
            care_unit=self.unit,
            doctor=self.doc_a,
            valid_from=datetime.date(2025, 1, 1),
        )

        today = timezone.localdate()
        # Doc A goes on leave, covered by Doc Cover
        DoctorCoverage.objects.create(
            care_unit=self.unit,
            absent_doctor=self.doc_a,
            covering_doctor=self.doc_cover,
            start_date=today - datetime.timedelta(days=1),
            end_date=today + datetime.timedelta(days=3),
            is_active=True,
        )

        # Doc Cover logs in and checks covering duty tab
        self.client.force_login(self.doc_cover)
        resp_cover = self.client.get(reverse("clients:client-list"), {"doctor": "covering"})
        self.assertEqual(resp_cover.status_code, 200)
        self.assertIn(self.client_patient, resp_cover.context["clients"])

    def test_centre_admin_allocation_panel_permissions_and_kpis(self):
        # Non-admin user gets 403 Forbidden
        self.client.force_login(self.doc_a)
        resp_denied = self.client.get(reverse("clients:centre-admin"))
        self.assertEqual(resp_denied.status_code, 403)

        # Unit Admin gets 200 OK
        self.client.force_login(self.admin_user)
        resp_ok = self.client.get(reverse("clients:centre-admin"))
        self.assertEqual(resp_ok.status_code, 200)
        self.assertContains(resp_ok, "Doctor Allocation & Caseload")
        self.assertContains(resp_ok, "Kurunegala Centre")

    def test_centre_admin_batch_assign_doctor(self):
        p1 = Client.objects.create(
            registration_number="TH-BATCH-01",
            full_name="Batch Patient 1",
            gender="M",
            date_of_birth="2014-01-01",
        )
        ClientCareUnit.objects.create(client=p1, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        p2 = Client.objects.create(
            registration_number="TH-BATCH-02",
            full_name="Batch Patient 2",
            gender="F",
            date_of_birth="2015-02-02",
        )
        ClientCareUnit.objects.create(client=p2, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)

        self.client.force_login(self.admin_user)
        post_data = {
            "action": "assign_doctor",
            "unit_id": self.unit.id,
            "target_doctor_id": self.doc_a.id,
            "client_ids": [p1.id, p2.id],
            "assignment_notes": "Assigned via batch tool",
        }
        resp = self.client.post(reverse("clients:centre-admin"), post_data)
        self.assertEqual(resp.status_code, 302)

        self.assertEqual(p1.assigned_doctor, self.doc_a)
        self.assertEqual(p2.assigned_doctor, self.doc_a)

    def test_centre_admin_smart_split_even_distribution(self):
        clients = []
        for i in range(4):
            c = Client.objects.create(
                registration_number=f"TH-SPLIT-{i+1:02d}",
                full_name=f"Split Patient {i+1}",
                gender="M",
                date_of_birth="2016-01-01",
            )
            ClientCareUnit.objects.create(client=c, unit=self.unit, role=ClientCareUnit.Role.PRIMARY, is_active=True)
            clients.append(c)

        self.client.force_login(self.admin_user)
        post_data = {
            "action": "smart_split",
            "unit_id": self.unit.id,
            "split_doctor_ids": [self.doc_a.id, self.doc_b.id],
            "client_ids": [c.id for c in clients],
        }
        resp = self.client.post(reverse("clients:centre-admin"), post_data)
        self.assertEqual(resp.status_code, 302)

        doc_a_count = ClientCareAssignment.objects.filter(care_unit=self.unit, doctor=self.doc_a, valid_to__isnull=True).count()
        doc_b_count = ClientCareAssignment.objects.filter(care_unit=self.unit, doctor=self.doc_b, valid_to__isnull=True).count()

        # 4 clients evenly split between 2 doctors = 2 each
        self.assertEqual(doc_a_count, 2)
        self.assertEqual(doc_b_count, 2)

    def test_centre_admin_coverage_add_and_end(self):
        today = timezone.localdate()
        self.client.force_login(self.admin_user)

        # 1. Add coverage
        add_data = {
            "action": "add_coverage",
            "unit_id": self.unit.id,
            "absent_doctor": self.doc_a.id,
            "covering_doctor": self.doc_cover.id,
            "start_date": str(today),
            "end_date": str(today + datetime.timedelta(days=7)),
            "reason": "Conference",
            "is_active": "on",
        }
        resp = self.client.post(reverse("clients:centre-admin"), add_data)
        self.assertEqual(resp.status_code, 302)
        coverage = DoctorCoverage.objects.filter(absent_doctor=self.doc_a, covering_doctor=self.doc_cover).first()
        self.assertIsNotNone(coverage)
        self.assertTrue(coverage.is_active)

        # 2. End coverage
        end_data = {
            "action": "end_coverage",
            "unit_id": self.unit.id,
            "coverage_id": coverage.id,
        }
        resp_end = self.client.post(reverse("clients:centre-admin"), end_data)
        self.assertEqual(resp_end.status_code, 302)
        coverage.refresh_from_db()
        self.assertFalse(coverage.is_active)

    def test_client_directory_page_size_and_pagination(self):
        self.client.force_login(self.admin_user)

        # 1. Default page_size is 50
        resp_default = self.client.get(reverse("clients:client-list"))
        self.assertEqual(resp_default.status_code, 200)
        self.assertEqual(resp_default.context["page_size"], 50)
        self.assertIn(50, resp_default.context["allowed_page_sizes"])

        # 2. Explicit allowed page_size (e.g. 25, 100)
        resp_25 = self.client.get(reverse("clients:client-list"), {"page_size": "25"})
        self.assertEqual(resp_25.status_code, 200)
        self.assertEqual(resp_25.context["page_size"], 25)

        resp_100 = self.client.get(reverse("clients:client-list"), {"page_size": "100"})
        self.assertEqual(resp_100.status_code, 200)
        self.assertEqual(resp_100.context["page_size"], 100)

        # 3. Invalid page_size falls back safely to default 50
        resp_invalid = self.client.get(reverse("clients:client-list"), {"page_size": "9999"})
        self.assertEqual(resp_invalid.status_code, 200)
        self.assertEqual(resp_invalid.context["page_size"], 50)



