from django.core.management.base import BaseCommand, CommandError

from wuixpose.core.ingest import boulder
from wuixpose.core.ingest.arcgis import ArcGISError

LAYERS = ("tracts", "structures")


def parse_bbox(value: str) -> boulder.Bbox:
    try:
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in value.split(","))
    except ValueError as exc:
        raise CommandError("--bbox must be min_lon,min_lat,max_lon,max_lat") from exc
    if not (min_lon < max_lon and min_lat < max_lat):
        raise CommandError("--bbox min values must be below max values")
    return min_lon, min_lat, max_lon, max_lat


class Command(BaseCommand):
    help = "Load Boulder County parcels (as tracts) and building footprints (as structures)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--layer",
            choices=LAYERS,
            action="append",
            help="Layer to load; repeat for both. Default: both.",
        )
        parser.add_argument(
            "--bbox",
            help="Only load features intersecting min_lon,min_lat,max_lon,max_lat (WGS 84).",
        )
        parser.add_argument("--page-size", type=int, default=2000)

    def handle(self, *args, layer=None, bbox=None, page_size, **options):
        layers = layer or list(LAYERS)
        box = parse_bbox(bbox) if bbox else None

        try:
            if "tracts" in layers:
                self.stdout.write("Loading parcels as tracts...")
                result = boulder.load_tracts(boulder.fetch_parcels(box, page_size=page_size))
                self.stdout.write(f"  tracts: {result}")
            if "structures" in layers:
                self.stdout.write("Loading building footprints as structures...")
                result = boulder.load_structures(boulder.fetch_footprints(box, page_size=page_size))
                self.stdout.write(f"  structures: {result}")
        except ArcGISError as exc:
            raise CommandError(f"Boulder County GIS request failed: {exc}") from exc

        # Either layer changing can change which tract a structure sits in.
        changed = boulder.assign_structure_tracts()
        self.stdout.write(self.style.SUCCESS(f"Done. {changed} structure-tract assignments changed."))
