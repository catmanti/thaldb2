import os
from datetime import date
from io import BytesIO
from typing import ClassVar

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.core.exceptions import ValidationError  # type: ignore[reportMissingModuleSource]
from django.core.files.base import ContentFile
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageOps

from .lookup import DiagnosisType, DS_Division, ThalassemiaUnit


# -------------------------------------------------------------------
#                      MAIN CLIENT MODEL
# -------------------------------------------------------------------
class Client(models.Model):
    """Basic demographic and registration details."""

    GENDER_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ("M", "Male"),
        ("F", "Female"),
    ]

    BLOOD_GROUP_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ("A+", "A+"),
        ("A-", "A-"),
        ("B+", "B+"),
        ("B-", "B-"),
        ("AB+", "AB+"),
        ("AB-", "AB-"),
        ("O+", "O+"),
        ("O-", "O-"),
    ]

    ETHNICITY_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ("Sinhalese", "Sinhalese"),
        ("Tamil", "Tamil"),
        ("SriLankanMoor", "Sri Lankan Moor"),
        ("Burger", "Burger"),
        ("Other", "Other"),
    ]
    # --- Demographics ---
    full_name = models.CharField(max_length=150)
    common_name = models.CharField(max_length=100, blank=True, null=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    ethnicity = models.CharField(max_length=100, choices=ETHNICITY_CHOICES, default="Sinhalese", blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True, null=True)
    nic_number = models.CharField(max_length=15, blank=True, null=True, unique=True)

    # --- Registration & clinical ---
    registration_number = models.CharField(max_length=50, unique=True)
    date_of_registration = models.DateField(blank=True, null=True)
    care_units = models.ManyToManyField(
        ThalassemiaUnit, through="ClientCareUnit", related_name="care_clients", blank=True
    )
    diagnosis = models.ForeignKey(
        DiagnosisType, on_delete=models.SET_NULL, blank=True, null=True, related_name="clients"
    )
    diagnosis_details = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Diagnosis Details / Genotype",
        help_text="e.g. Genotype mutation (IVS1-5 G>C homozygous, Cd 41/42), or clinical variant notes",
    )
    # --- Social details ---
    marital_status = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"category": "marital_status"},
        related_name="clients_marital_status",
    )
    occupation = models.CharField(max_length=100, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    ds_division = models.ForeignKey(DS_Division, on_delete=models.SET_NULL, blank=True, null=True)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    photo = models.ImageField(upload_to="client_photos/", blank=True, null=True)
    guardian_name_1 = models.CharField(max_length=100, blank=True, null=True)
    guardian_name_2 = models.CharField(max_length=100, blank=True, null=True)
    guardian_contact_number_1 = models.CharField(max_length=20, blank=True, null=True)
    guardian_contact_number_2 = models.CharField(max_length=20, blank=True, null=True)
    diagnosis_date = models.DateField(blank=True, null=True)
    HB_level_at_diagnosis = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    date_first_transfused = models.DateField(blank=True, null=True)
    date_iron_chelation_started = models.DateField(blank=True, null=True)
    transfusion_regimen = models.CharField(max_length=200, blank=True, null=True) #better use integerfield for transfusion frequency in dates
    # add hb_level_to_be_kept
    allergic_history = models.TextField(blank=True, null=True)
    special_note = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.registration_number} : {self.full_name}"

    def get_absolute_url(self):
        return reverse("clients:client-detail", kwargs={"pk": self.pk})


    @property
    def precise_age(self):
        # Get today's date in a timezone-aware format (optional, but good practice)
        today = timezone.localdate()
        # Calculate the difference using relativedelta
        if self.date_of_birth is None:
            return {"years": "", "months": "", "days": ""}
        diff = relativedelta(today, self.date_of_birth)

        # The result is an object with .years, .months, and .days attributes
        return {"years": diff.years, "months": diff.months, "days": diff.days}

    @property
    def age_string(self):
        age_data = self.precise_age
        return f"{age_data['years']}y, {age_data['months']}m, {age_data['days']}d"
    @property
    def initials_with_last_name(self):
        full_name_parts = self.full_name.split()
        if len(full_name_parts) == 0:
            return ""
        elif len(full_name_parts) == 1:
            return full_name_parts[0][0].upper() + "."
        else:
            initials = ""
            for part in full_name_parts[:-1]:
                initials += part[0].upper() + ". "
            initials += full_name_parts[-1]
            return initials
    @property
    def primary_care_unit(self):
        """Returns the active primary care unit, or falls back to the most recent primary care unit."""
        if hasattr(self, "_prefetched_objects_cache") and "care_links" in self._prefetched_objects_cache:
            # 1. Search for active primary unit first
            for link in self.care_links.all():
                if link.is_active and link.role == ClientCareUnit.Role.PRIMARY:
                    return link.unit
            # 2. Fall back to most recent primary unit
            primary_links = [l for l in self.care_links.all() if l.role == ClientCareUnit.Role.PRIMARY]
            if primary_links:
                return primary_links[0].unit
            return None

        primary_link = (
            self.care_links.filter(role=ClientCareUnit.Role.PRIMARY)
            .order_by("-is_active", "-start_date", "-id")
            .select_related("unit")
            .first()
        )
        return primary_link.unit if primary_link else None

    @property
    def is_active_care(self) -> bool:
        """Returns True if the client is currently receiving active care."""
        if hasattr(self, "_prefetched_objects_cache") and "care_links" in self._prefetched_objects_cache:
            return any(link.is_active for link in self.care_links.all())
        return self.care_links.filter(is_active=True).exists()

    @property
    def has_bmt(self) -> bool:
        """Returns True if the client has any recorded bone marrow transplant."""
        return self.bmt_records.exists()

    @property
    def assigned_doctor(self):
        """Returns the currently active assigned primary doctor for the patient's primary care unit."""
        if hasattr(self, "active_doctor_assignment_list"):
            unit = self.primary_care_unit
            for assign in self.active_doctor_assignment_list:
                if not unit or assign.care_unit_id == unit.id:
                    return assign.doctor
            return None

        unit = self.primary_care_unit
        if not unit:
            return None
        active_assignment = (
            self.doctor_assignments.filter(care_unit=unit, valid_to__isnull=True)
            .select_related("doctor")
            .first()
        )
        return active_assignment.doctor if active_assignment else None

    @property
    def current_duty_doctor(self):
        """Returns the assigned doctor, or the covering doctor if the assigned doctor is currently on leave."""
        doctor = self.assigned_doctor
        if not doctor:
            return None

        today = timezone.localdate()
        coverage = (
            doctor.leave_delegations.filter(start_date__lte=today, end_date__gte=today, is_active=True)
            .select_related("covering_doctor")
            .first()
        )
        return coverage.covering_doctor if coverage else doctor

    @property
    def is_doctor_on_leave(self) -> bool:
        """Returns True if the assigned doctor is currently covered by another doctor due to leave."""
        doctor = self.assigned_doctor
        if not doctor:
            return False
        today = timezone.localdate()
        return doctor.leave_delegations.filter(start_date__lte=today, end_date__gte=today, is_active=True).exists()

    def save(self, *args, **kwargs):
        # Auto-crop to center square 1:1 and resize uploaded photo to 400x400 JPEG
        if self.photo and hasattr(self.photo, "file"):
            try:
                img = Image.open(self.photo)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img_cropped = ImageOps.fit(img, (400, 400), Image.Resampling.LANCZOS)
                buffer = BytesIO()
                img_cropped.save(buffer, format="JPEG", quality=85, optimize=True)
                file_name = os.path.basename(self.photo.name)
                self.photo.save(file_name, ContentFile(buffer.getvalue()), save=False)
            except Exception:
                pass  # Fallback gracefully if non-image data

        super().save(*args, **kwargs)

    class Meta:
        ordering = ["full_name"]
        indexes = [
            GinIndex(
                name="client_full_name_trgm_idx",
                fields=["full_name"],
                opclasses=["gin_trgm_ops"],
            ),
            GinIndex(
                name="client_common_name_trgm_idx",
                fields=["common_name"],
                opclasses=["gin_trgm_ops"],
            ),
        ]


class ClientCareUnit(models.Model):
    class Role(models.TextChoices):
        PRIMARY = "PRIMARY", "Primary"
        SHARED = "SHARED", "Shared"
        REFERRAL = "REFERRAL", "Referral"

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="care_links")
    unit = models.ForeignKey(ThalassemiaUnit, on_delete=models.CASCADE, related_name="client_links")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PRIMARY)
    start_date = models.DateField(default=timezone.localdate)
    end_date = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True, null=True)

    def clean(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be earlier than start date."})

        # Allow inactive primary care unit if client is deceased, post-BMT, or end_date is recorded
        if self.role == self.Role.PRIMARY and not self.is_active:
            if not self.end_date and not (
                hasattr(self, "client")
                and (
                    hasattr(self.client, "death_record")
                    or (hasattr(self.client, "bmt_records") and self.client.bmt_records.filter(is_successful=True).exists())
                )
            ):
                raise ValidationError({"is_active": "Primary care unit must be active unless patient is discharged, deceased, or post-BMT."})

    def __str__(self):
        return f"{self.client.registration_number} - {self.unit.name} ({self.role})"

    class Meta:
        ordering = ["client", "-is_active", "role", "start_date"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F("start_date")),
                name="check_clientcareunit_end_date_after_start",
            ),
            models.UniqueConstraint(
                fields=["client", "unit"],
                condition=Q(is_active=True),
                name="uniq_active_client_unit_link",
            ),
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(is_active=True, role="PRIMARY"),
                name="uniq_active_primary_unit_per_client",
            ),
        ]


# -------------------------------------------------------------------
#                   DOCTOR ASSIGNMENT & LEAVE COVERAGE
# -------------------------------------------------------------------
class ClientCareAssignment(models.Model):
    """Tracks primary physician assignment history for a patient at a specific unit."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="doctor_assignments")
    care_unit = models.ForeignKey(ThalassemiaUnit, on_delete=models.CASCADE, related_name="client_assignments")
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assigned_clients",
        limit_choices_to={"role": "DOCTOR"},
        verbose_name="Assigned Doctor",
    )
    valid_from = models.DateField(default=timezone.localdate, verbose_name="Assignment Start Date")
    valid_to = models.DateField(blank=True, null=True, verbose_name="Assignment End Date")
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments_made",
        verbose_name="Assigned By",
    )
    notes = models.TextField(blank=True, null=True, help_text="e.g. Initial triage, Transitioned from Pediatrics")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["client", "-valid_from", "-id"]
        verbose_name = "Doctor Assignment"
        verbose_name_plural = "Doctor Assignments"
        constraints = [
            models.CheckConstraint(
                condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                name="check_assignment_valid_to_after_from",
            ),
            models.UniqueConstraint(
                fields=["client", "care_unit"],
                condition=Q(valid_to__isnull=True),
                name="uniq_active_doctor_per_client_unit",
            ),
        ]

    def clean(self):
        super().clean()
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": "End date (valid_to) cannot be earlier than start date (valid_from)."})

    def close_assignment(self, end_date=None):
        """Helper to close an active assignment before assigning a new doctor."""
        self.valid_to = end_date or timezone.localdate()
        self.save(update_fields=["valid_to", "updated_at"])

    @classmethod
    def assign_doctor(cls, client, care_unit, doctor, assigned_by=None, notes=None, start_date=None):
        """Safely assigns a doctor to a patient at a care unit, closing any existing active assignment."""
        start = start_date or timezone.localdate()
        active_qs = cls.objects.filter(client=client, care_unit=care_unit, valid_to__isnull=True)
        for old in active_qs:
            if old.doctor_id == doctor.id:
                return old
            old.close_assignment(end_date=start)

        return cls.objects.create(
            client=client,
            care_unit=care_unit,
            doctor=doctor,
            valid_from=start,
            assigned_by=assigned_by,
            notes=notes or "",
        )

    def __str__(self):
        doc_name = self.doctor.get_full_name() or self.doctor.email
        status_str = f"{self.valid_from} to Present" if not self.valid_to else f"{self.valid_from} to {self.valid_to}"
        return f"{self.client.registration_number} -> Dr. {doc_name} ({status_str})"


class DoctorCoverage(models.Model):
    """Temporary clinical cross-coverage when a doctor is on leave or locum duty."""

    care_unit = models.ForeignKey(ThalassemiaUnit, on_delete=models.CASCADE, related_name="doctor_coverages")
    absent_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="leave_delegations",
        limit_choices_to={"role": "DOCTOR"},
        verbose_name="Doctor on Leave",
    )
    covering_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="covering_delegations",
        limit_choices_to={"role": "DOCTOR"},
        verbose_name="Covering Doctor",
    )
    start_date = models.DateField(default=timezone.localdate, verbose_name="Leave Start Date")
    end_date = models.DateField(verbose_name="Leave End Date")
    reason = models.CharField(max_length=200, blank=True, null=True, help_text="e.g. Annual Leave, Medical Leave, Conference")
    is_active = models.BooleanField(default=True, verbose_name="Coverage Active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-start_date", "-id"]
        verbose_name = "Doctor Leave Coverage"
        verbose_name_plural = "Doctor Leave Coverages"
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="check_doctor_coverage_end_after_start",
            ),
        ]

    def clean(self):
        super().clean()
        if self.absent_doctor_id and self.covering_doctor_id and self.absent_doctor_id == self.covering_doctor_id:
            raise ValidationError({"covering_doctor": "Covering doctor cannot be the same as the doctor on leave."})
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date cannot be earlier than start date."})

    def __str__(self):
        absent_name = self.absent_doctor.get_full_name() or self.absent_doctor.email
        covering_name = self.covering_doctor.get_full_name() or self.covering_doctor.email
        return f"Dr. {covering_name} covering for Dr. {absent_name} ({self.start_date} to {self.end_date})"


# -------------------------------------------------------------------
#                      DEATH RECORD
# -------------------------------------------------------------------
class ClientDeath(models.Model):
    """Stores client death details."""

    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name="death_record")
    date_of_death = models.DateField(blank=True, null=True)
    cause_of_death = models.TextField(blank=True, null=True)
    postmortem_findings = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Death record: {self.client.full_name}"
# -------------------------------------------------------------------
#                      UNDERWENT BONE MARROW TRANSPLANT
# -------------------------------------------------------------------
class ClientBMT(models.Model):
    """Stores client bone marrow transplant (HSCT) details."""

    client = models.ForeignKey(
        Client, on_delete=models.CASCADE, related_name="bmt_records"
    )
    date_of_bmt = models.DateField(blank=True, null=True, verbose_name="Date of BMT / HSCT")
    is_successful = models.BooleanField(
        default=True,
        verbose_name="Transplant Successful / Transfusion Free",
        help_text="True if patient achieved sustained donor engraftment",
    )
    institution_name = models.CharField(
        max_length=200,
        blank=True,
        null=True,
        verbose_name="Transplant Center / Hospital",
    )
    donor_type = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Donor Type",
        help_text="e.g. Matched Sibling (MSD), Matched Unrelated (MUD), Haploidentical",
    )
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date_of_bmt"]
        verbose_name = "Bone Marrow Transplant"
        verbose_name_plural = "Bone Marrow Transplants"

    def __str__(self):
        return f"BMT on {self.date_of_bmt} - {self.client.full_name}"
# -------------------------------------------------------------------
#                      TRANSFER RECORD
# -------------------------------------------------------------------
class ClientTransfer(models.Model):
    """Records client transfer details."""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="transfer_record")
    transferred_unit = models.ForeignKey(
        ThalassemiaUnit,
        on_delete=models.SET_NULL,
        null=True,
        related_name="transferred_clients",
    )
    date_of_transfer = models.DateField(default=timezone.localdate)
    reason = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.client.full_name} transferred to {self.transferred_unit}"


# -------------------------------------------------------------------
#                      FAMILY MEMBERS
# -------------------------------------------------------------------
class FamilyMember(models.Model):
    """FAMILY MEMBERS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="family_members")
    relationship = models.CharField(
        max_length=50,
        choices=[
            ("Father", "Father"),
            ("Mother", "Mother"),
            ("Sibling", "Sibling"),
            ("Other", "Other"),
        ],
        default="Other",
    )
    name = models.CharField(max_length=100)
    birth_day = models.DateField(blank=True, null=True)
    diagnosis = models.ForeignKey(DiagnosisType, on_delete=models.SET_NULL, blank=True, null=True)
    related_client = models.ForeignKey(Client, on_delete=models.SET_NULL, blank=True, null=True, related_name="as_family_member")  # if the family member is also a client
    is_carrier = models.BooleanField(default=False)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.relationship})"
