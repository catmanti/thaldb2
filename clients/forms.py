from django import forms
from django.utils import timezone

from .models import (
    Admission,
    Choice,
    Client,
    District,
    DS_Division,
    Investigation,
    InvestigationType,
    Laboratory,
    Province,
    Transfusion,
)


class ClientForm(forms.ModelForm):
    province = forms.ModelChoiceField(
        queryset=Province.objects.all(),
        required=False,
        empty_label="-- Select Province --",
        widget=forms.Select(
            attrs={
                "class": "select select-bordered w-full",
                "hx-get": "/clients/load-districts/",
                "hx-target": "#id_district",
                "hx-trigger": "change",
            }
        ),
    )
    district = forms.ModelChoiceField(
        queryset=District.objects.none(),
        required=False,
        empty_label="-- Select District --",
        widget=forms.Select(
            attrs={
                "class": "select select-bordered w-full",
                "hx-get": "/clients/load-ds-divisions/",
                "hx-target": "#id_ds_division",
                "hx-trigger": "change",
            }
        ),
    )

    class Meta:
        model = Client
        fields = [
            "registration_number",
            "full_name",
            "common_name",
            "gender",
            "ethnicity",
            "date_of_birth",
            "blood_group",
            "nic_number",
            "date_of_registration",
            "diagnosis",
            "diagnosis_details",
            "marital_status",
            "occupation",
            "address",
            "ds_division",
            "contact_number",
            "email",
            "photo",
            "guardian_name_1",
            "guardian_contact_number_1",
            "guardian_name_2",
            "guardian_contact_number_2",
            "diagnosis_date",
            "HB_level_at_diagnosis",
            "date_first_transfused",
            "date_iron_chelation_started",
            "transfusion_regimen",
            "allergic_history",
            "special_note",
        ]
        widgets = {
            "registration_number": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "e.g. TH-2026-001"}),
            "full_name": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Full legal name"}),
            "common_name": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Known name / Nickname"}),
            "gender": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "ethnicity": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "date_of_birth": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "blood_group": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "nic_number": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "National Identity Card No."}),
            "date_of_registration": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "diagnosis": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "diagnosis_details": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Genotype / mutation details (e.g. IVS1-5, Cd 41/42)"}),
            "marital_status": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "occupation": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "address": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 2}),
            "ds_division": forms.Select(attrs={"class": "select select-bordered w-full", "id": "id_ds_division"}),
            "contact_number": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "07XXXXXXXX"}),
            "email": forms.EmailInput(attrs={"class": "input input-bordered w-full"}),
            "photo": forms.FileInput(attrs={"class": "file-input file-input-bordered w-full"}),
            "guardian_name_1": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "guardian_contact_number_1": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "guardian_name_2": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "guardian_contact_number_2": forms.TextInput(attrs={"class": "input input-bordered w-full"}),
            "diagnosis_date": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "HB_level_at_diagnosis": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.1"}),
            "date_first_transfused": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "date_iron_chelation_started": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "transfusion_regimen": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "e.g. Every 3 weeks"}),
            "allergic_history": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 2}),
            "special_note": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("date_of_registration") and not self.instance.pk:
            self.initial["date_of_registration"] = timezone.localdate()

        # Handle cascading dropdown initial values when editing or bound
        if "province" in self.data:
            try:
                province_id = int(self.data.get("province"))
                self.fields["district"].queryset = District.objects.filter(province_id=province_id).order_by("name")
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.ds_division:
            self.fields["province"].initial = self.instance.ds_division.district.province
            self.fields["district"].queryset = District.objects.filter(
                province=self.instance.ds_division.district.province
            ).order_by("name")
            self.fields["district"].initial = self.instance.ds_division.district

        if "district" in self.data:
            try:
                district_id = int(self.data.get("district"))
                self.fields["ds_division"].queryset = DS_Division.objects.filter(district_id=district_id).order_by("name")
            except (ValueError, TypeError):
                pass
        elif self.instance.pk and self.instance.ds_division:
            self.fields["ds_division"].queryset = DS_Division.objects.filter(
                district=self.instance.ds_division.district
            ).order_by("name")


class AdmissionForm(forms.ModelForm):
    class Meta:
        model = Admission
        fields = [
            "date_of_admission",
            "reason_for_admission",
            "is_routine_day_transfusion",
            "date_of_discharge",
            "outcome",
            "notes",
        ]
        widgets = {
            "date_of_admission": forms.DateTimeInput(
                attrs={"class": "input input-bordered w-full", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "reason_for_admission": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "is_routine_day_transfusion": forms.CheckboxInput(attrs={"class": "checkbox checkbox-primary"}),
            "date_of_discharge": forms.DateTimeInput(
                attrs={"class": "input input-bordered w-full", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "outcome": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Discharge status / outcome"}),
            "notes": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if not self.initial.get("date_of_admission"):
                self.initial["date_of_admission"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
            if not self.initial.get("reason_for_admission"):
                bt_choice = Choice.objects.filter(category="admission_reason", name="Blood Transfusion").first()
                if bt_choice:
                    self.initial["reason_for_admission"] = bt_choice.pk
                    self.initial["is_routine_day_transfusion"] = True
        else:
            if self.instance.date_of_admission:
                self.initial["date_of_admission"] = timezone.localtime(self.instance.date_of_admission).strftime("%Y-%m-%dT%H:%M")
            if self.instance.date_of_discharge:
                self.initial["date_of_discharge"] = timezone.localtime(self.instance.date_of_discharge).strftime("%Y-%m-%dT%H:%M")


class TransfusionForm(forms.ModelForm):
    class Meta:
        model = Transfusion
        fields = [
            "date_of_transfusion",
            "pre_HB_level",
            "post_HB_level",
            "amount_of_blood",
            "special_type",
            "next_date_given",
            "reaction",
            "checked_by",
            "remarks",
        ]
        widgets = {
            "date_of_transfusion": forms.DateTimeInput(
                attrs={"class": "input input-bordered w-full", "type": "datetime-local"},
                format="%Y-%m-%dT%H:%M",
            ),
            "pre_HB_level": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.1", "placeholder": "9.0"}),
            "post_HB_level": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.1"}),
            "amount_of_blood": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "10", "placeholder": "250"}),
            "special_type": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "next_date_given": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "reaction": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "None"}),
            "checked_by": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Staff Name / Designation"}),
            "remarks": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if not self.initial.get("date_of_transfusion"):
                self.initial["date_of_transfusion"] = timezone.localtime().strftime("%Y-%m-%dT%H:%M")
            if not self.initial.get("special_type"):
                lrb_choice = Choice.objects.filter(category="special_blood_type", name="LRB").first()
                if lrb_choice:
                    self.initial["special_type"] = lrb_choice.pk
            if user and not self.initial.get("checked_by"):
                self.initial["checked_by"] = user.first_name or user.get_short_name() or user.username
        else:
            if self.instance.date_of_transfusion:
                self.initial["date_of_transfusion"] = timezone.localtime(self.instance.date_of_transfusion).strftime("%Y-%m-%dT%H:%M")


class InvestigationForm(forms.ModelForm):
    class Meta:
        model = Investigation
        fields = [
            "investigation_type",
            "date_done",
            "value",
            "text_value",
            "laboratory",
            "notes",
        ]
        widgets = {
            "investigation_type": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "date_done": forms.DateInput(attrs={"class": "input input-bordered w-full", "type": "date"}),
            "value": forms.NumberInput(attrs={"class": "input input-bordered w-full", "step": "0.01", "placeholder": "Numeric value (e.g. 2450.5)"}),
            "text_value": forms.TextInput(attrs={"class": "input input-bordered w-full", "placeholder": "Text result (e.g. Non-reactive, Normal)"}),
            "laboratory": forms.Select(attrs={"class": "select select-bordered w-full"}),
            "notes": forms.Textarea(attrs={"class": "textarea textarea-bordered w-full", "rows": 3, "placeholder": "Clinical observations / comments"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.initial.get("date_done") and not self.instance.pk:
            self.initial["date_done"] = timezone.localdate()

