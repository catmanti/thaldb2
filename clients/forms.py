from django import forms
from django.utils import timezone

from .models import Client, District, DS_Division, Province


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
