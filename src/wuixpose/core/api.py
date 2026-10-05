"""Read-only JSON for the map: what's loaded, and details for a clicked tract or structure.

Shapes themselves go to the map as vector tiles (see tiles.py); these endpoints carry the
attributes a popup or side panel needs.
"""

from django.contrib.gis.db.models import Extent
from django.contrib.gis.geos import GEOSGeometry
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Structure, Tract

# NAD83 / CONUS Albers, an equal-area projection in meters, for measuring areas in the US.
EQUAL_AREA_SRID = 5070
SQ_M_PER_ACRE = 4046.8564224
SQ_FT_PER_SQ_M = 10.763910417


def area_sq_m(geom: GEOSGeometry) -> float:
    return geom.transform(EQUAL_AREA_SRID, clone=True).area


class TractSerializer(serializers.ModelSerializer):
    county_apns = serializers.SerializerMethodField()
    area_acres = serializers.SerializerMethodField()
    structure_ids = serializers.SerializerMethodField()

    class Meta:
        model = Tract
        fields = ("id", "county_apns", "area_acres", "structure_ids")

    def get_county_apns(self, tract: Tract) -> list[str]:
        return [i.value for i in tract.identifiers.all() if i.valid_to is None]

    def get_area_acres(self, tract: Tract) -> float:
        return round(area_sq_m(tract.geom) / SQ_M_PER_ACRE, 2)

    def get_structure_ids(self, tract: Tract) -> list[int]:
        return list(tract.structures.order_by("pk").values_list("pk", flat=True))


class StructureSerializer(serializers.ModelSerializer):
    footprint_sq_ft = serializers.SerializerMethodField()

    class Meta:
        model = Structure
        fields = ("id", "source", "source_id", "tract", "footprint_sq_ft")

    def get_footprint_sq_ft(self, structure: Structure) -> int:
        return round(area_sq_m(structure.geom) * SQ_FT_PER_SQ_M)


@api_view(["GET"])
def tract_detail(request, pk: int):
    tract = get_object_or_404(Tract.objects.prefetch_related("identifiers"), pk=pk)
    return Response(TractSerializer(tract).data)


@api_view(["GET"])
def structure_detail(request, pk: int):
    return Response(StructureSerializer(get_object_or_404(Structure, pk=pk)).data)


@api_view(["GET"])
def summary(request):
    """Counts and the bounding box of loaded tracts, so the map can open on the data."""
    extent = Tract.objects.aggregate(extent=Extent("geom"))["extent"]
    return Response(
        {
            "tract_count": Tract.objects.count(),
            "structure_count": Structure.objects.count(),
            "bbox": list(extent) if extent else None,  # [min_lon, min_lat, max_lon, max_lat]
        }
    )
