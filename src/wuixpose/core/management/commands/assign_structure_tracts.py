from django.core.management.base import BaseCommand

from wuixpose.core.ingest import boulder


class Command(BaseCommand):
    help = "Assign structures to tracts by footprint overlap, reconsidering what changed since the last run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Reconsider every structure, e.g. after changing the assignment rule.",
        )

    def handle(self, *args, full, **options):
        result = boulder.assign_structure_tracts(full=full)
        self.stdout.write(self.style.SUCCESS(f"{result}."))
