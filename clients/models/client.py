import os
from datetime import date
from io import BytesIO
from typing import ClassVar

from dateutil.relativedelta import relativedelta
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
        if hasattr(self, "_prefetched_objects_cache") and "care_links" in self._prefetched_objects_cache:
            for link in self.care_links.all():
                if link.is_active and link.role == ClientCareUnit.Role.PRIMARY:
                    return link.unit
            return None
        primary_link = (
            self.care_links.filter(is_active=True, role=ClientCareUnit.Role.PRIMARY)
            .select_related("unit")
            .first()
        )
        return primary_link.unit if primary_link else None

    @property
    def has_bmt(self) -> bool:
        """Returns True if the client has any recorded bone marrow transplant."""
        return self.bmt_records.exists()

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

        if self.role == self.Role.PRIMARY and not self.is_active:
            raise ValidationError({"is_active": "Primary care unit must be active."})

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
