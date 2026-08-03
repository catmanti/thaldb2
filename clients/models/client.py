from datetime import date
from typing import ClassVar

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError  # type: ignore[reportMissingModuleSource]
from django.db import models
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone

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
    transfusion_regimen = models.CharField(max_length=200, blank=True, null=True)
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
        return f"{age_data['years']} years, {age_data['months']} months, and {age_data['days']} days"

    @property
    def primary_care_unit(self):
        primary_link = self.care_links.filter(is_active=True, role=ClientCareUnit.Role.PRIMARY).first()
        return primary_link.unit if primary_link else None

    class Meta:
        ordering = ["full_name"]


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
    date_of_death = models.DateField()
    cause_of_death = models.TextField(blank=True, null=True)
    postmortem_findings = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Death record: {self.client.full_name}"


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
