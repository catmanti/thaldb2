from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from clients.models import Choice


class Command(BaseCommand):
    help = "Populate the Choice model using choices.txt"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default=str(settings.BASE_DIR / "clients" / "choices.txt"),
            help="Path to the choices.txt file",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"])
        if not file_path.exists():
            self.stderr.write(self.style.ERROR(f"File not found: {file_path}"))
            return

        current_category = None
        created_count = 0
        existing_count = 0

        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                raw_line = line.rstrip()
                if not raw_line:
                    continue

                # Check if it's a category line (no leading spaces)
                if not line.startswith(" ") and not line.startswith("\t"):
                    current_category = raw_line.strip()
                else:
                    choice_name = raw_line.strip()
                    if current_category and choice_name:
                        choice, created = Choice.objects.get_or_create(
                            category=current_category,
                            name=choice_name,
                        )
                        if created:
                            created_count += 1
                            self.stdout.write(
                                self.style.SUCCESS(f"Created Choice: [{current_category}] -> '{choice_name}'")
                            )
                        else:
                            existing_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully processed choices. Created: {created_count}, Already Existed: {existing_count}"
            )
        )
