import re
import urllib.request
from html.parser import HTMLParser

from django.core.management.base import BaseCommand

from clients.models import District, DS_Division, Province


class WikiTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.cell_index = 0
        self.tables = []
        self.current_table = []
        self.current_row = []
        self.current_ds_list = []
        self.in_li = False
        self.current_li = []
        self.cell_texts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "table" and "wikitable" in attrs_dict.get("class", ""):
            self.in_table = True
            self.current_table = []
        elif self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
            self.cell_texts = []
            self.cell_index = 0
        elif self.in_row and tag in ("th", "td"):
            self.in_cell = True
            self.cell_index += 1
            self.current_cell_data = []
        elif self.in_cell and tag == "li":
            self.in_li = True
            self.current_li = []

    def handle_endtag(self, tag):
        if tag == "table" and self.in_table:
            self.in_table = False
            self.tables.append(self.current_table)
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row:
                self.current_table.append(self.current_row)
        elif tag in ("th", "td") and self.in_cell:
            self.in_cell = False
            cell_text = " ".join("".join(self.current_cell_data).split())
            if self.current_ds_list:
                self.current_row.append((cell_text, list(self.current_ds_list)))
                self.current_ds_list = []
            else:
                self.current_row.append((cell_text, []))
        elif tag == "li" and self.in_li:
            self.in_li = False
            text = " ".join("".join(self.current_li).split())
            if text:
                self.current_ds_list.append(text)

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell_data.append(data)
            if self.in_li:
                self.current_li.append(data)


class Command(BaseCommand):
    help = "Populate Province, District, and DS_Division from Wikipedia"

    def handle(self, *args, **options):
        url = "https://en.wikipedia.org/wiki/Divisional_secretariats_of_Sri_Lanka"
        self.stdout.write(f"Fetching location data from {url}...")

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            html_content = urllib.request.urlopen(req).read().decode("utf-8")
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch Wikipedia page: {e}"))
            return

        parser = WikiTableParser()
        parser.feed(html_content)

        if not parser.tables:
            self.stderr.write(self.style.ERROR("No wikitables found on Wikipedia page."))
            return

        table = parser.tables[0]
        current_province = None

        prov_count = 0
        dist_count = 0
        ds_count = 0

        for row in table[1:]:
            # If row has 5 cells, cell 0 is Province, cell 2 is District, cell 4 is DS list
            # If row has 3 cells, cell 0 is District, cell 2 is DS list
            if len(row) == 5:
                province_name = row[0][0].strip()
                district_name = row[2][0].strip()
                ds_items = row[4][1]
            elif len(row) == 3:
                province_name = current_province_name
                district_name = row[0][0].strip()
                ds_items = row[2][1]
            else:
                continue

            current_province_name = province_name

            # Create or get Province
            province_obj, p_created = Province.objects.get_or_create(name=province_name)
            if p_created:
                prov_count += 1

            # Create or get District
            district_obj, d_created = District.objects.get_or_create(
                name=district_name,
                defaults={"province": province_obj},
            )
            if d_created:
                dist_count += 1

            # Process DS Divisions
            for raw_ds in ds_items:
                # Strip parentheses numbers like '(30)'
                clean_ds = re.sub(r"\s*\(\d+\)", "", raw_ds).strip()
                if clean_ds:
                    ds_obj, ds_created = DS_Division.objects.get_or_create(
                        name=clean_ds,
                        defaults={"district": district_obj},
                    )
                    if ds_created:
                        ds_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully populated location data:\n"
                f"  - Provinces created: {prov_count} (Total in DB: {Province.objects.count()})\n"
                f"  - Districts created: {dist_count} (Total in DB: {District.objects.count()})\n"
                f"  - DS Divisions created: {ds_count} (Total in DB: {DS_Division.objects.count()})"
            )
        )
