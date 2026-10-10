import csv
import difflib
import re
from datetime import date, datetime
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from clients.models import (
    Client,
    ClientBMT,
    ClientCareUnit,
    ClientDeath,
    DiagnosisType,
    District,
    DS_Division,
    ThalassemiaUnit,
)


class Command(BaseCommand):
    help = "Import thalassemia patient data from CSV into the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_file",
            nargs="?",
            default="Thalassaemia_Patient_Data.csv",
            help="Path to CSV file (default: Thalassaemia_Patient_Data.csv)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simulate the import and roll back changes at the end.",
        )
        parser.add_argument(
            "--update-first",
            action="store_true",
            default=True,
            help="Update client #1 (T-1) if already present (default: True).",
        )

    def handle(self, *args, **options):
        csv_file_path = options["csv_file"]
        is_dry_run = options["dry_run"]
        update_first = options["update_first"]

        self.stdout.write(self.style.NOTICE(f"Loading patients from {csv_file_path}... (Dry-Run: {is_dry_run})"))

        # Setup lookup mappings
        diagnosis_map = self._setup_diagnoses()
        unit_map = self._setup_units()
        ds_map, district_map = self._setup_locations()

        with open(csv_file_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        self.stdout.write(f"Total rows found in CSV: {len(rows)}")

        stats = {
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "deaths_created": 0,
            "bmts_created": 0,
            "units_linked": 0,
            "ds_divisions_matched": 0,
            "errors": 0,
        }

        try:
            with transaction.atomic():
                for row in rows:
                    try:
                        self._process_row(
                            row=row,
                            diagnosis_map=diagnosis_map,
                            unit_map=unit_map,
                            ds_map=ds_map,
                            district_map=district_map,
                            update_first=update_first,
                            stats=stats,
                        )
                    except Exception as e:
                        stats["errors"] += 1
                        self.stderr.write(self.style.ERROR(f"Error on Row No {row.get('No')}: {e}"))
                        raise e

                if is_dry_run:
                    self.stdout.write(self.style.WARNING("DRY RUN completed: Rolling back transaction..."))
                    transaction.set_rollback(True)
                else:
                    self.stdout.write(self.style.SUCCESS("Import completed successfully! Transaction committed."))

        except Exception as e:
            if not is_dry_run:
                self.stderr.write(self.style.ERROR(f"Import aborted due to error: {e}"))
                return

        self._print_summary(stats, is_dry_run)

    # -------------------------------------------------------------------------
    # Setup helpers
    # -------------------------------------------------------------------------
    def _setup_diagnoses(self) -> dict[str, DiagnosisType]:
        """Ensure standard diagnoses exist and build a lookup dict."""
        diagnoses = [
            ("Beta Thalassemia Major", "BTM", ["beta thalassaemia major", "beta thalassemia major", "β thal major"]),
            ("E Beta Thalassemia", "EBT", ["e beta thalassemia", "e beta thalassaemia", "e/β thal"]),
            ("Thalassemia Intermedia", "TInt", ["thalassaemia intermedia", "thalassemia intermedia"]),
            ("Sickle Cell disease", "SCD", ["sickle cell disease", "sickle cell"]),
            ("Delta Beta Beta Thalassemia", "DBBT", ["delta beta beta thalassemia", "delta beta beta thalassaemia"]),
            ("Hb H Disease", "HBH", ["hb h disease", "hbh"]),
            ("Alpha Beta Thalassemia", "ABT", ["alpha beta thalassemia", "alpha beta thalassaemia"]),
            ("Other", "Other", ["other"]),
        ]

        lookup = {}
        for canonical_name, short_code, aliases in diagnoses:
            obj, _ = DiagnosisType.objects.get_or_create(
                name=canonical_name,
                defaults={"short_name": short_code},
            )
            lookup[canonical_name.lower()] = obj
            for alias in aliases:
                lookup[alias.lower()] = obj

        return lookup

    def _setup_units(self) -> dict[str, ThalassemiaUnit]:
        """Ensure healthcare units exist and build a lookup dict."""
        unit_specs = [
            ("Kurunegala TH", ["kurunegala", "kurunegala th"]),
            ("Ragama TH", ["ragama", "ragama th"]),
            ("Anuradhapura TH", ["anuradhapura", "anuradhapura th"]),
            ("Kandy TH", ["kandy", "kandy th"]),
            ("Peradeniya TH", ["peradeniya", "peradeniya th"]),
            ("Polonnaruwa TH", ["polonnaruwa", "polonnaruwa th"]),
            ("Chilaw TH", ["chilaw", "chilaw th"]),
            ("Trincomalee TH", ["trincomalee", "trincomalee th"]),
            ("Ratnapura TH", ["ratnapura", "rathnapura", "ratnapura th", "rathnapura th"]),
        ]

        lookup = {}
        for canonical_name, aliases in unit_specs:
            obj, _ = ThalassemiaUnit.objects.get_or_create(name=canonical_name)
            for alias in aliases:
                lookup[alias.lower()] = obj

        return lookup

    def _setup_locations(self):
        """Prepare District and DS Division lookups."""
        district_aliases = {
            "puttlam": "Puttalam",
            "mathale": "Matale",
            "trinco": "Trincomalee",
            "kaluthara": "Kalutara",
            "rathnapuraya": "Ratnapura",
            "wawniya": "Vavuniya",
            "nuwaraeliya": "Nuwara Eliya",
            "hambanthota": "Hambantota",
            "kegalle": "Kegalle",
        }

        districts = {d.name.lower(): d for d in District.objects.all()}
        for alias, target in district_aliases.items():
            if target.lower() in districts:
                districts[alias.lower()] = districts[target.lower()]

        all_divs = list(DS_Division.objects.select_related("district").all())
        div_map = {d.name.lower(): d for d in all_divs}

        # Common spelling variants in Sri Lankan registry
        custom_div_map = {
            "ganewaththa": "Ganewatta",
            "galagedara": "Galagedera",
            "anamanduwa": "Anamaduwa",
            "ahetuwewa": "Ehetuwewa",
            "bamunakottuwa": "Bamunakotuwa",
            "kotawehera": "Kobeigane",
            "maho": "Mahawa",
            "nawagaththegama": "Nawagattegama",
            "harisapaththuwa": "Harispattuwa",
            "wavniyawa": "Vavuniya",
            "katugasthota": "Harispattuwa",
            "kandy": "Four Gravets & Gangawata Korale",
            "anuradhapura": "Nuwaragam Palatha Central",
            "paduwasnuwara - west": "Panduwasnuwara West",
            "paduwasnuwara - east": "Panduwasnuwara East",
            "kuliyapitiya - west": "Kuliyapitiya West",
            "kuliyapitiya - east": "Kuliyapitiya East",
        }
        for alias, target in custom_div_map.items():
            if target.lower() in div_map:
                div_map[alias.lower()] = div_map[target.lower()]

        return div_map, districts

    # -------------------------------------------------------------------------
    # Parsing Helpers
    # -------------------------------------------------------------------------
    def _parse_date(self, date_str: str) -> tuple[Optional[date], Optional[str]]:
        """Parses various date formats from the CSV."""
        if not date_str:
            return None, None
        s = date_str.strip()
        if s.upper() in ("NA", "N/A", "NO", "NONE", ""):
            return None, None

        # Typo correction: 26/091993 -> 26/09/1993
        s = re.sub(r"(\d{2})/(\d{2})(\d{4})", r"\1/\2/\3", s)

        # Invalid month: 05.00.2003
        if "00.2003" in s or ".00." in s:
            return date(2003, 1, 5), f"Original recorded date: {s}"

        # Relative note: 14 yrs
        if "yr" in s.lower():
            return None, f"Reported age: {s}"

        for fmt in [
            "%d %B %Y",
            "%d %b %Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y-%m-%d",
            "%d.%m.%Y",
            "%m/%d/%Y",
            "%d %B %y",
            "%d/%m/%y",
        ]:
            try:
                return datetime.strptime(s, fmt).date(), None
            except ValueError:
                pass

        return None, f"Unparsed date: {s}"

    def _normalize_blood_group(self, bg_str: str) -> Optional[str]:
        if not bg_str:
            return None
        s = bg_str.strip().lower()
        if s in ("na", "n/a", "no", "unknown"):
            return None

        mapping = {
            "a pos": "A+", "a positive": "A+", "a+": "A+",
            "a neg": "A-", "a negative": "A-", "a-": "A-",
            "b pos": "B+", "b positive": "B+", "b+": "B+",
            "b neg": "B-", "b negative": "B-", "b-": "B-",
            "ab pos": "AB+", "ab positive": "AB+", "ab+": "AB+",
            "ab neg": "AB-", "ab negative": "AB-", "ab-": "AB-",
            "o pos": "O+", "o positive": "O+", "o+": "O+",
            "o neg": "O-", "o negative": "O-", "o-": "O-",
        }
        return mapping.get(s)

    def _normalize_gender(self, sex_str: str) -> str:
        s = (sex_str or "").strip().lower()
        if s in ("female", "f"):
            return "F"
        return "M"

    def _normalize_ethnicity(self, nat_str: str) -> str:
        s = (nat_str or "").strip().lower()
        if "tamil" in s:
            return "Tamil"
        elif "muslim" in s or "moor" in s:
            return "SriLankanMoor"
        return "Sinhalese"

    # -------------------------------------------------------------------------
    # Row Processing
    # -------------------------------------------------------------------------
    def _process_row(
        self,
        row: dict,
        diagnosis_map: dict,
        unit_map: dict,
        ds_map: dict,
        district_map: dict,
        update_first: bool,
        stats: dict,
    ):
        raw_no = row["No"].strip()
        reg_number = f"T-{raw_no}"

        # Combine first and last name
        fname = row.get("Fname", "").strip()
        lname = row.get("Lname", "").strip()
        full_name = f"{fname} {lname}".strip() or f"Patient {reg_number}"

        # Common / call name
        common_name = fname.split()[0] if fname else ""

        # Status & Death check
        status_raw = (row.get("Status") or "").strip().lower()
        is_dead = status_raw == "dead" or bool((row.get("Date_of_death") or "").strip())
        is_bmt = "bmt" in status_raw

        # Dates
        dob, dob_note = self._parse_date(row.get("DOB", ""))
        dod, dod_note = self._parse_date(row.get("Date_of_death", ""))

        # Blood Group & Demographics
        gender = self._normalize_gender(row.get("Sex", ""))
        blood_group = self._normalize_blood_group(row.get("Blood Group", ""))
        ethnicity = self._normalize_ethnicity(row.get("Nationality", ""))

        # Diagnosis
        diag_str = (row.get("Diagnosis") or "").strip().lower()
        diagnosis_obj = diagnosis_map.get(diag_str) or diagnosis_map.get("other")
        diag_detail = (row.get("Diagnosis_Detail") or "").strip() or None

        # Diagnosis Year & Age at Diagnosis
        diag_year_str = (row.get("Diagnosis Year") or "").strip()
        diag_date = None
        if diag_year_str.isdigit() and len(diag_year_str) == 4:
            diag_date = date(int(diag_year_str), 1, 1)

        age_at_diag = (row.get("Age at Diagnosis") or "").strip()
        notes_parts = []
        if age_at_diag:
            notes_parts.append(f"Age at diagnosis: {age_at_diag}")
        if dob_note:
            notes_parts.append(dob_note)
        special_note = "; ".join(notes_parts) if notes_parts else ""

        # Address & DS Division
        raw_address = (row.get("Address") or "").strip()
        address = "" if raw_address.lower() in ("no", "na", "n/a", "none") else raw_address

        ag_div_str = (row.get("AG Division") or "").strip().lower()
        dist_str = (row.get("District") or "").strip().lower()
        ds_division = ds_map.get(ag_div_str)
        if not ds_division and ag_div_str:
            norm_ag = ag_div_str.replace(" ", "").replace("-", "")
            for name_key, div_obj in ds_map.items():
                if norm_ag == name_key.replace(" ", "").replace("-", ""):
                    ds_division = div_obj
                    break
        if ds_division:
            stats["ds_divisions_matched"] += 1

        # Check existing
        existing_client = Client.objects.filter(registration_number=reg_number).first()
        if not existing_client and raw_no == "1":
            existing_client = Client.objects.filter(id=1).first()

        client_data = {
            "full_name": full_name,
            "common_name": common_name,
            "gender": gender,
            "ethnicity": ethnicity,
            "date_of_birth": dob,
            "blood_group": blood_group,
            "diagnosis": diagnosis_obj,
            "diagnosis_details": diag_detail,
            "diagnosis_date": diag_date,
            "address": address or (f"AG Division: {row.get('AG Division')}, District: {row.get('District')}" if not address else address),
            "ds_division": ds_division,
            "special_note": special_note,
        }

        if existing_client:
            if raw_no == "1" and not update_first:
                stats["skipped"] += 1
                return
            for key, val in client_data.items():
                setattr(existing_client, key, val)
            existing_client.registration_number = reg_number
            existing_client.save()
            client = existing_client
            stats["updated"] += 1
        else:
            client = Client.objects.create(registration_number=reg_number, **client_data)
            stats["created"] += 1

        # Care Unit Link
        primary_unit_str = (row.get("Primary_Unit") or "").strip().lower()
        unit_obj = unit_map.get(primary_unit_str) or unit_map.get("kurunegala th")
        if unit_obj:
            initial_start_date = dob or (dod if is_dead and dod else date(1990, 1, 1))
            if is_dead and dod and initial_start_date > dod:
                initial_start_date = dod

            should_be_active = not is_dead and not is_bmt
            care_link, created = ClientCareUnit.objects.get_or_create(
                client=client,
                unit=unit_obj,
                defaults={
                    "role": ClientCareUnit.Role.PRIMARY,
                    "is_active": should_be_active,
                    "start_date": initial_start_date,
                    "end_date": dod if is_dead else None,
                },
            )
            # If existed, update status and reconcile dates
            care_link.is_active = should_be_active
            if is_dead and dod:
                if care_link.start_date > dod:
                    care_link.start_date = dob if dob and dob <= dod else dod
                care_link.end_date = dod
            care_link.save()
            stats["units_linked"] += 1

        # Death Record
        if is_dead:
            cause_of_death_raw = (row.get("Cause_of_death") or "").strip()
            cause = "" if cause_of_death_raw.upper() in ("NA", "N/A", "NO", "NONE") else cause_of_death_raw
            death_notes = dod_note or ""

            ClientDeath.objects.update_or_create(
                client=client,
                defaults={
                    "date_of_death": dod,
                    "cause_of_death": cause,
                    "notes": death_notes or None,
                },
            )
            stats["deaths_created"] += 1

        # BMT Record
        if is_bmt:
            if not client.bmt_records.exists():
                ClientBMT.objects.create(
                    client=client,
                    date_of_bmt=None,
                    institution_name="Imported Registry Record",
                    is_successful=True,
                    notes="Registry status: Underwent BMT",
                )
                stats["bmts_created"] += 1

    def _print_summary(self, stats: dict, is_dry_run: bool):
        mode = "DRY RUN SUMMARY" if is_dry_run else "IMPORT SUMMARY"
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.SUCCESS(f"  {mode}"))
        self.stdout.write("=" * 50)
        self.stdout.write(f"  Clients Created          : {stats['created']}")
        self.stdout.write(f"  Clients Updated          : {stats['updated']}")
        self.stdout.write(f"  Clients Skipped          : {stats['skipped']}")
        self.stdout.write(f"  Death Records Created    : {stats['deaths_created']}")
        self.stdout.write(f"  BMT Records Created      : {stats['bmts_created']}")
        self.stdout.write(f"  Care Units Assigned      : {stats['units_linked']}")
        self.stdout.write(f"  DS Divisions Matched     : {stats['ds_divisions_matched']}")
        self.stdout.write(f"  Errors Encountered       : {stats['errors']}")
        self.stdout.write("=" * 50 + "\n")
