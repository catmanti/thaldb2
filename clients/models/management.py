from django.db import models
from django.urls import reverse

from .client import Client

class TimeStampedModel(models.Model):
    """Time stamped model for all models in clients app."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class ComplicationType(TimeStampedModel):
    """COMPLICATIONS TYPES like DM, HYPOTHYROIDISM etc."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class Complication(TimeStampedModel):
    """CLIENT'S COMPLICATIONS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_complications")
    complication = models.ForeignKey(ComplicationType, on_delete=models.SET_NULL, null=True)
    detected_date = models.DateField()
    status = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"category": "complication_status"},
    )
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.complication} - {self.client.full_name}"


class Vaccination(TimeStampedModel):
    """VACCINATIONS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="vaccinations")
    vaccine_name = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"category": "vaccine_name"},
    )

    date_given = models.DateField()
    dose = models.CharField(max_length=100, blank=True, null=True)
    next_dose_date = models.DateField(blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.vaccine_name} ({self.client.full_name})"


class InvestigationType(TimeStampedModel):
    """Represents a type of investigation, e.g., FBC, LFT."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    reference_range = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name


class Investigation(TimeStampedModel):
    """INVESTIGATIONS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_investigations")
    date_done = models.DateField()
    investigation_type = models.ForeignKey(InvestigationType, on_delete=models.SET_NULL, null=True, blank=True)
    value = models.FloatField(blank=True, null=True)
    text_value = models.CharField(max_length=100, blank=True, null=True) # Use this text when value is not a number, eg: Reactive, Non-reactive.
    laboratory_name = models.CharField(max_length=100, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.investigation_type} - {self.client.full_name}"


class GrowthRecord(TimeStampedModel):
    """GROWTH RECORDS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="growth_records")
    date_measured = models.DateField()
    type = models.ForeignKey("Choice", on_delete=models.SET_NULL, null=True, limit_choices_to={"category": "growth"})
    value = models.DecimalField(max_digits=6, decimal_places=2)
    percentile = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.type} - {self.value} ({self.client.full_name})"


class Admission(TimeStampedModel):
    """HOSPITAL ADMISSIONS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_admissions")
    date_of_admission = models.DateField()
    reason_for_admission = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"category": "admission_reason"},
    )
    date_of_discharge = models.DateField(blank=True, null=True)
    outcome = models.CharField(max_length=200, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Admission on {self.date_of_admission} - {self.client.initials_with_last_name}"

    def get_absolute_url(self):
        """Return the client detail URL after admission operations."""
        return reverse("clients:client-detail", kwargs={"pk": self.client.pk})


class Transfusion(TimeStampedModel):
    """BLOOD TRANSFUSIONS"""

    # Client of the transfusion is the client of the admission
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name="blood_transfusions")
    date_of_transfusion = models.DateField()
    pre_HB_level = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True, default=9.0)
    post_HB_level = models.DecimalField(max_digits=4, decimal_places=1, blank=True, null=True)
    WBC_count = models.DecimalField(max_digits=8, decimal_places=2, blank=True, null=True)
    platelet_count = models.DecimalField(max_digits=8, decimal_places=1, blank=True, null=True)
    amount_of_blood = models.DecimalField(max_digits=6, decimal_places=2, blank=True, null=True)
    special_type = models.ForeignKey(
        "Choice", on_delete=models.SET_NULL, null=True, limit_choices_to={"category": "special_blood_type"}, blank=True
    )
    next_date_given = models.DateField(blank=True, null=True)
    reaction = models.CharField(max_length=200, blank=True, null=True, default="None")
    checked_by = models.CharField(max_length=100, blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Transfusion on {self.date_of_transfusion} - {self.admission.client.full_name}"


class ClinicVisit(TimeStampedModel):
    """CLINIC VISITS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="clinic_visits")
    date_visit = models.DateField()
    problem = models.TextField(blank=True, null=True)
    clinic_type = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"category": "clinic_type"},
    )
    action = models.TextField(blank=True, null=True)
    referral = models.CharField(max_length=200, blank=True, null=True)
    next_visit_date = models.DateField(blank=True, null=True)
    doctor_name = models.CharField(max_length=100, blank=True, null=True)
    follow_up_needed = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Clinic visit - {self.client.full_name} ({self.date_visit})"
