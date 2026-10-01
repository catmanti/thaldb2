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
        self.user = User.objects.create_user(email="doctor@hospital.lk", password="pass123")
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-999",
            full_name="Test Thalassemia Patient",
            gender="M",
            date_of_birth="2015-05-10",
        )
        self.reason_choice = Choice.objects.create(
            category="admission_reason",
            name="Blood Transfusion",
        )

    def test_admission_and_transfusion_creation(self):
        self.client.force_login(self.user)

        # 1. Create Admission via HTMX POST
        create_adm_url = reverse("clients:admission-create", kwargs={"client_id": self.client_obj.pk})
        resp = self.client.post(
            create_adm_url,
            {
                "date_of_admission": timezone.localdate(),
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
                "date_of_transfusion": timezone.localdate(),
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


class InvestigationWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="doctor@hospital.lk", password="pass123")
        self.client_obj = Client.objects.create(
            registration_number="TH-2026-777",
            full_name="Investigation Test Patient",
            gender="F",
            date_of_birth="2016-08-15",
        )
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
