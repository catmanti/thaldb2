import datetime
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone

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


class Laboratory(TimeStampedModel):
    """Represents a medical laboratory / diagnostic facility."""

    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(max_length=20, blank=True, null=True)
    contact_number = models.CharField(max_length=20, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "Laboratories"


class InvestigationType(TimeStampedModel):
    """Represents a type of investigation, e.g., FBC, LFT."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    unit = models.CharField(max_length=50, blank=True, null=True)
    reference_range = models.CharField(max_length=100, blank=True, null=True)
    recommended_interval_months = models.PositiveIntegerField(
        blank=True,
        null=True,
        help_text="Recommended test frequency in months (e.g. 1 = Monthly, 3 = Quarterly, 12 = Yearly)",
    )

    def __str__(self):
        if self.recommended_interval_months:
            return f"{self.name} (Every {self.recommended_interval_months}m)"
        return self.name


class Investigation(TimeStampedModel):
    """INVESTIGATIONS"""

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="client_investigations")
    date_done = models.DateField()
    investigation_type = models.ForeignKey(InvestigationType, on_delete=models.SET_NULL, null=True, blank=True)
    value = models.FloatField(blank=True, null=True)
    text_value = models.CharField(max_length=100, blank=True, null=True)  # Use when value is text (e.g. Reactive/Non-reactive)
    laboratory = models.ForeignKey(Laboratory, on_delete=models.SET_NULL, null=True, blank=True, related_name="investigations")
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.investigation_type} - {self.client.full_name}"

    @property
    def next_due_date(self):
        """Calculates next due date based on date_done and recommended_interval_months."""
        if not self.investigation_type or not self.investigation_type.recommended_interval_months or not self.date_done:
            return None

        import datetime

        d = self.date_done
        if isinstance(d, str):
            try:
                d = datetime.date.fromisoformat(d)
            except ValueError:
                return None

        months = self.investigation_type.recommended_interval_months
        month = d.month - 1 + months
        year = d.year + month // 12
        month = month % 12 + 1
        day = min(
            d.day,
            [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1],
        )
        return datetime.date(year, month, day)

    @property
    def surveillance_status(self):
        """Returns dict with status, label, badge_class, and overdue_days."""
        due = self.next_due_date
        if not due:
            return None

        from django.utils import timezone

        today = timezone.localdate()
        days_diff = (due - today).days

        if days_diff < 0:
            overdue_days = abs(days_diff)
            return {
                "status": "overdue",
                "label": f"Overdue by {overdue_days}d",
                "short_label": f"Overdue ({overdue_days}d)",
                "badge_class": "badge-error",
                "days_diff": days_diff,
                "due_date": due,
                "is_overdue": True,
            }
        elif days_diff <= 30:
            return {
                "status": "due_soon",
                "label": f"Due in {days_diff}d",
                "short_label": f"Due ({days_diff}d)",
                "badge_class": "badge-warning",
                "days_diff": days_diff,
                "due_date": due,
                "is_due_soon": True,
            }
        else:
            return {
                "status": "up_to_date",
                "label": "Up to date",
                "short_label": "Up to date",
                "badge_class": "badge-success badge-outline",
                "days_diff": days_diff,
                "due_date": due,
                "is_up_to_date": True,
            }


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
    date_of_admission = models.DateTimeField(default=timezone.now)
    reason_for_admission = models.ForeignKey(
        "Choice",
        on_delete=models.SET_NULL,
        null=True,
        limit_choices_to={"category": "admission_reason"},
    )
    date_of_discharge = models.DateTimeField(blank=True, null=True)
    is_routine_day_transfusion = models.BooleanField(
        default=False,
        verbose_name="Routine Day Transfusion (Day-Care)",
        help_text="If checked, automatically marks discharge upon recording transfusion completion.",
    )
    outcome = models.CharField(max_length=200, blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        adm_date_str = timezone.localtime(self.date_of_admission).strftime("%Y-%m-%d %H:%M") if self.date_of_admission else "N/A"
        return f"Admission on {adm_date_str} - {self.client.initials_with_last_name}"

    def get_absolute_url(self):
        """Return the client detail URL after admission operations."""
        return reverse("clients:client-detail", kwargs={"pk": self.client.pk})

    @property
    def is_active(self):
        return self.date_of_discharge is None

    def clean(self):
        super().clean()
        if self.date_of_discharge and self.date_of_admission:
            if self.date_of_discharge < self.date_of_admission:
                raise ValidationError({
                    "date_of_discharge": "Discharge date/time cannot be earlier than admission date/time."
                })

    def mark_discharged(self, discharge_time=None, outcome="Discharged"):
        """Mark this admission as discharged."""
        self.date_of_discharge = discharge_time or timezone.now()
        if outcome and not self.outcome:
            self.outcome = outcome
        self.save(update_fields=["date_of_discharge", "outcome", "updated_at"])


class Transfusion(TimeStampedModel):
    """BLOOD TRANSFUSIONS"""

    # Client of the transfusion is the client of the admission
    admission = models.ForeignKey(Admission, on_delete=models.CASCADE, related_name="blood_transfusions")
    date_of_transfusion = models.DateTimeField(default=timezone.now)
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
        tr_date_str = timezone.localtime(self.date_of_transfusion).strftime("%Y-%m-%d %H:%M") if self.date_of_transfusion else "N/A"
        return f"Transfusion on {tr_date_str} - {self.admission.client.full_name}"

    def clean(self):
        super().clean()
        if hasattr(self, "admission") and self.admission and self.date_of_transfusion:
            adm = self.admission
            if self.date_of_transfusion < adm.date_of_admission:
                adm_str = timezone.localtime(adm.date_of_admission).strftime("%Y-%m-%d %H:%M")
                raise ValidationError({
                    "date_of_transfusion": f"Transfusion date/time cannot be earlier than admission ({adm_str})."
                })
            if adm.date_of_discharge:
                if self.date_of_transfusion > adm.date_of_discharge:
                    dis_str = timezone.localtime(adm.date_of_discharge).strftime("%Y-%m-%d %H:%M")
                    raise ValidationError({
                        "date_of_transfusion": f"Transfusion date/time cannot be after discharge ({dis_str})."
                    })
            else:
                # Active admission: cannot be in the future (with 5 min grace period for clock drift)
                now = timezone.now() + datetime.timedelta(minutes=5)
                if self.date_of_transfusion > now:
                    raise ValidationError({
                        "date_of_transfusion": "Transfusion date/time cannot be in the future."
                    })


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
