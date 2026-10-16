"""Read-only JSON for the map: the rules it follows, what's loaded, details for a clicked tract or
structure, and search.

Shapes themselves go to the map as vector tiles (see tiles.py); these endpoints carry the
attributes a popup or side panel needs.
"""

import re

from django.contrib.gis.db.models import Extent
from django.contrib.gis.geos import GEOSGeometry
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .constants import EQUAL_AREA_SRID, SQ_FT_PER_SQ_M, SQ_M_PER_ACRE
from .display import address_line1, address_line2
from .models import Address, Structure, Tract
from .search import MIN_QUERY_LENGTH, search_addresses
from .zones import RINGS


def area_sq_m(geom: GEOSGeometry) -> float:
    return geom.transform(EQUAL_AREA_SRID, clone=True).area


def county_apns(tract: Tract) -> list[str]:
    return [i.value for i in tract.identifiers.all() if i.tracked_to is None]


class AddressSerializer(serializers.ModelSerializer):
    line1 = serializers.SerializerMethodField()
    line2 = serializers.SerializerMethodField()
    lon = serializers.FloatField(source="geom.x")
    lat = serializers.FloatField(source="geom.y")

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        model = Address
        fields = ("id", "line1", "line2", "lon", "lat")

    def get_line1(self, address: Address) -> str:
        return address_line1(address)

    def get_line2(self, address: Address) -> str:
        return address_line2(address)


def _natural(text: str) -> tuple:
    """A sort key that orders runs of digits as numbers: "#9" before "#10"."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", text) if part
    )


def _address_order(address: Address) -> tuple:
    """Street, then house number, then unit, numbers in numeric order: 9 Main St before 10 Main St."""
    return (address.street, _natural(address.number), _natural(address.unit))


def tract_addresses(tract_id: int | None) -> list[dict]:
    if tract_id is None:
        return []
    addresses = sorted(Address.objects.current().filter(tract_id=tract_id), key=_address_order)
    return AddressSerializer(addresses, many=True).data


class TractSerializer(serializers.ModelSerializer):
    addresses = serializers.SerializerMethodField()
    county_apns = serializers.SerializerMethodField()
    area_acres = serializers.SerializerMethodField()
    structure_ids = serializers.SerializerMethodField()

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        model = Tract
        fields = ("id", "addresses", "county_apns", "area_acres", "structure_ids")

    def get_addresses(self, tract: Tract) -> list[dict]:
        return tract_addresses(tract.pk)

    def get_county_apns(self, tract: Tract) -> list[str]:
        return county_apns(tract)

    def get_area_acres(self, tract: Tract) -> float:
        return round(area_sq_m(tract.geom) / SQ_M_PER_ACRE, 2)

    def get_structure_ids(self, tract: Tract) -> list[int]:
        return list(tract.structures.order_by("pk").values_list("pk", flat=True))


class StructureSerializer(serializers.ModelSerializer):
    tract_county_apns = serializers.SerializerMethodField()
    footprint_sq_ft = serializers.SerializerMethodField()
    # Addresses aren't linked to structures yet, so a structure shows its lot's.
    tract_addresses = serializers.SerializerMethodField()

    class Meta:  # pyright: ignore[reportIncompatibleVariableOverride]
        model = Structure
        fields = (
            "id",
            "source",
            "source_id",
            "tract",
            "tract_county_apns",
            "tract_addresses",
            "footprint_sq_ft",
        )

    def get_tract_county_apns(self, structure: Structure) -> list[str]:
        return county_apns(structure.tract) if structure.tract else []

    def get_tract_addresses(self, structure: Structure) -> list[dict]:
        return tract_addresses(structure.tract_id)

    def get_footprint_sq_ft(self, structure: Structure) -> int:
        return round(area_sq_m(structure.geom) * SQ_FT_PER_SQ_M)


@api_view(["GET"])
def tract_detail(request, pk: int):
    tract = get_object_or_404(Tract.objects.prefetch_related("identifiers"), pk=pk)
    return Response(TractSerializer(tract).data)


@api_view(["GET"])
def structure_detail(request, pk: int):
    structure = get_object_or_404(
        Structure.objects.select_related("tract").prefetch_related("tract__identifiers"), pk=pk
    )
    return Response(StructureSerializer(structure).data)


class SearchResultSerializer(AddressSerializer):
    class Meta(AddressSerializer.Meta):
        fields = (*AddressSerializer.Meta.fields, "tract")


@api_view(["GET"])
def search(request):
    """Current addresses best matching ?q=, best first. Empty for a missing or too-short query."""
    results = search_addresses(request.query_params.get("q", ""))
    return Response({"results": SearchResultSerializer(results, many=True).data})


@api_view(["GET"])
def config(request):
    """Rules the server sets that the map UI follows, so the UI never keeps its own copy."""
    return Response(
        {
            "search": {"min_query_length": MIN_QUERY_LENGTH},
            # Nearest the structure first.
            "zones": {
                "rings": [
                    {"key": ring.key, "inner_ft": ring.inner_ft, "outer_ft": ring.outer_ft}
                    for ring in RINGS
                ]
            },
        }
    )


@api_view(["GET"])
def summary(request):
    """Counts and the bounding box of loaded tracts, so the map can open on the data."""
    extent = Tract.objects.aggregate(extent=Extent("geom"))["extent"]
    return Response(
        {
            "tract_count": Tract.objects.count(),
            "structure_count": Structure.objects.count(),
            "address_count": Address.objects.current().count(),
            "bbox": list(extent) if extent else None,  # [min_lon, min_lat, max_lon, max_lat]
        }
    )
