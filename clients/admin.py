from django.contrib import admin

from .models import (
    Admission,
    Choice,
    Client,
    ClientCareUnit,
    ClientDeath,
    ClientTransfer,
    ClinicVisit,
    Complication,
    ComplicationType,
    DiagnosisType,
    District,
    DS_Division,
    Drug,
    DrugName,
    FamilyMember,
    GrowthRecord,
    Investigation,
    InvestigationType,
    Laboratory,
    Province,
    ThalassemiaUnit,
    Transfusion,
    Vaccination,
)


@admin.register(ClientDeath)
class ClientDeathAdmin(admin.ModelAdmin):
    """Admin for ClientDeath"""

    list_display = ["client", "date_of_death", "cause_of_death", "notes"]
    list_filter = ["date_of_death"]
    search_fields = ["client__full_name", "cause_of_death", "notes"]
    ordering = ["-date_of_death"]


@admin.register(ClientTransfer)
class ClientTransferAdmin(admin.ModelAdmin):
    """Admin for ClientTransfer"""

    list_display = ["client", "date_of_transfer", "transferred_unit", "reason"]
    list_filter = ["date_of_transfer", "transferred_unit"]
    search_fields = ["client__full_name", "transferred_unit__name", "reason"]
    ordering = ["-date_of_transfer"]


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    """Admin for FamilyMember"""

    list_display = ["client", "name", "relationship", "birth_day", "is_carrier"]
    list_filter = ["relationship", "is_carrier", "birth_day"]
    search_fields = ["client__full_name", "name"]
    ordering = ["-birth_day"]


@admin.register(Choice)
class ChoiceAdmin(admin.ModelAdmin):
    """Admin for Choice"""

    list_display = ["category", "name"]
    list_filter = ["category"]
    search_fields = ["name", "category"]
    ordering = ["name"]


@admin.register(Province)
class ProvinceAdmin(admin.ModelAdmin):
    """Admin for Province"""

    list_display = ["name"]
    search_fields = ["name"]
    ordering = ["name"]


@admin.register(District)
class DistrictAdmin(admin.ModelAdmin):
    """Admin for District"""

    list_display = ["name", "province"]
    list_filter = ["province"]
    search_fields = ["name", "province__name"]
    ordering = ["name"]


@admin.register(DS_Division)
class DS_DivisionAdmin(admin.ModelAdmin):
    """Admin for DS_Division"""

    list_display = ["name", "district"]
    list_filter = ["district"]
    search_fields = ["name", "district__name"]
    ordering = ["name"]


@admin.register(ThalassemiaUnit)
class ThalassemiaUnitAdmin(admin.ModelAdmin):
    """Admin for ThalassemiaUnit"""

    list_display = ["name", "ds_division"]
    list_filter = ["ds_division"]
    search_fields = ["name", "ds_division__name"]
    ordering = ["name"]


@admin.register(DiagnosisType)
class DiagnosisTypeAdmin(admin.ModelAdmin):
    """Admin for DiagnosisType"""

    list_display = ["name", "short_name", "icd_code"]
    search_fields = ["name", "short_name", "icd_code"]
    ordering = ["name"]


@admin.register(ClientCareUnit)
class ClientCareUnitAdmin(admin.ModelAdmin):
    """Admin for ClientCareUnit"""

    list_display = ["client", "unit", "role", "start_date", "end_date", "is_active"]
    list_filter = ["role", "is_active", "unit"]
    search_fields = ["client__full_name", "unit__name"]
    ordering = ["client", "-is_active", "start_date"]


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Admin for Client"""

    list_display = ["registration_number", "full_name", "date_of_birth", "gender", "contact_number", "diagnosis"]
    list_filter = ["gender", "blood_group", "diagnosis", "ethnicity"]
    search_fields = ["registration_number", "full_name", "contact_number", "nic_number"]
    ordering = ["full_name"]


@admin.register(ComplicationType)
class ComplicationTypeAdmin(admin.ModelAdmin):
    """Admin for ComplicationType"""

    list_display = ["name", "description"]
    search_fields = ["name", "description"]
    ordering = ["name"]


@admin.register(Complication)
class ComplicationAdmin(admin.ModelAdmin):
    """Admin for Complication"""

    list_display = ["client", "complication", "detected_date", "status", "remarks"]
    list_filter = ["complication", "status", "detected_date"]
    search_fields = ["client__full_name", "complication__name", "remarks"]
    ordering = ["-detected_date"]


@admin.register(Vaccination)
class VaccinationAdmin(admin.ModelAdmin):
    """Admin for Vaccination"""

    list_display = ["client", "vaccine_name", "date_given", "dose", "next_dose_date"]
    list_filter = ["vaccine_name", "date_given", "next_dose_date"]
    search_fields = ["client__full_name", "vaccine_name__name"]
    ordering = ["-date_given"]


@admin.register(InvestigationType)
class InvestigationTypeAdmin(admin.ModelAdmin):
    """Admin for InvestigationType"""

    list_display = ["name", "unit", "reference_range"]
    list_filter = ["unit"]
    search_fields = ["name", "unit", "reference_range"]
    ordering = ["name"]


@admin.register(Laboratory)
class LaboratoryAdmin(admin.ModelAdmin):
    """Admin for Laboratory"""

    list_display = ["name", "code", "contact_number"]
    search_fields = ["name", "code"]
    ordering = ["name"]


@admin.register(Investigation)
class InvestigationAdmin(admin.ModelAdmin):
    """Admin for Investigation"""

    list_display = ["client", "investigation_type", "date_done", "value", "text_value", "laboratory"]
    list_filter = ["investigation_type", "laboratory", "date_done"]
    search_fields = ["client__full_name", "investigation_type__name", "laboratory__name"]
    ordering = ["-date_done"]


@admin.register(GrowthRecord)
class GrowthRecordAdmin(admin.ModelAdmin):
    """Admin for GrowthRecord"""

    list_display = ["client", "type", "value", "percentile", "date_measured"]
    list_filter = ["type", "date_measured"]
    search_fields = ["client__full_name", "type__name"]
    ordering = ["-date_measured"]


@admin.register(Admission)
class AdmissionAdmin(admin.ModelAdmin):
    """Admin for Admission"""

    list_display = ["client", "date_of_admission", "reason_for_admission", "date_of_discharge"]
    list_filter = ["reason_for_admission", "date_of_admission", "date_of_discharge"]
    search_fields = ["client__full_name", "reason_for_admission__name"]
    ordering = ["-date_of_admission"]


@admin.register(Transfusion)
class TransfusionAdmin(admin.ModelAdmin):
    """Admin for Transfusion"""

    list_display = ["admission", "date_of_transfusion", "pre_HB_level", "post_HB_level", "amount_of_blood", "special_type"]
    list_filter = ["special_type", "date_of_transfusion"]
    search_fields = ["admission__client__full_name", "special_type__name"]
    ordering = ["-date_of_transfusion"]


@admin.register(ClinicVisit)
class ClinicVisitAdmin(admin.ModelAdmin):
    """Admin for ClinicVisit"""

    list_display = ["client", "date_visit", "clinic_type", "next_visit_date", "doctor_name"]
    list_filter = ["clinic_type", "date_visit", "next_visit_date"]
    search_fields = ["client__full_name", "clinic_type__name", "doctor_name"]
    ordering = ["-date_visit"]


@admin.register(DrugName)
class DrugNameAdmin(admin.ModelAdmin):
    """Admin for DrugName"""

    list_display = ["name", "dose", "regimen"]
    search_fields = ["name"]
    ordering = ["name"]


@admin.register(Drug)
class DrugAdmin(admin.ModelAdmin):
    """Admin for Drug"""

    list_display = ["client", "drug_name", "date_prescribed", "dose", "regimen", "duration"]
    list_filter = ["drug_name", "date_prescribed"]
    search_fields = ["client__full_name", "drug_name__name"]
    ordering = ["-date_prescribed"]
