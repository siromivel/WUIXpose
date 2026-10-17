from django.core.management.base import BaseCommand

from wuixpose.core import zones


class Command(BaseCommand):
    help = "Draw zones around structures, redrawing those whose footprint changed since the last run."

    def add_arguments(self, parser):
        parser.add_argument(
            "--full",
            action="store_true",
            help="Redraw every structure's zones.",
        )

    def handle(self, *args, full, **options):
        result = zones.build_zones(full=full)
        self.stdout.write(self.style.SUCCESS(f"{result}."))
