from datetime import date

import pytest
from django.contrib.gis.geos import Point

from wuixpose.core.ingest import boulder
from wuixpose.core.ingest.geometry import point_from_geojson
from wuixpose.core.models import Address, RejectedFeature
from wuixpose.core.models.tracts import STORAGE_SRID, TractIdentifier

from .factories import ORIGIN, address_props, box, feature, point_feature

# Display


@pytest.mark.parametrize(
    ("number", "street", "unit", "line1"),
    [
        ("1172", "VALLEY LN", "", "1172 Valley Ln"),
        ("4500", "S 19TH ST", "APT N304", "4500 S 19th St Apt N304"),
        ("2615", "COUNTY ROAD 128J", "", "2615 County Road 128J"),
        ("2211", "PRATT ST", "#7D", "2211 Pratt St #7D"),
        ("1172 1/2", "MCCASLIN BLVD", "", "1172 1/2 McCaslin Blvd"),
        ("40", "O'NEIL WAY", "", "40 O'Neil Way"),
    ],
)
def test_display_line1(number, street, unit, line1):
    assert Address(number=number, street=street, unit=unit).display_line1() == line1


@pytest.mark.parametrize(
    ("jurisdiction", "zip_code", "line2"),
    [
        ("UNINCORPORATED BOULDER COUNTY", "80302", "Unincorporated Boulder County, CO 80302"),
        ("LONGMONT", "80501", "Longmont, CO 80501"),
        ("", "", "CO"),
    ],
)
def test_display_line2(jurisdiction, zip_code, line2):
    assert Address(jurisdiction=jurisdiction, state="CO", zip_code=zip_code).display_line2() == line2


# Loading


@pytest.mark.django_db
def test_load_addresses_normalizes_county_fields():
    result = boulder.load_addresses(
        [
            point_feature(
                address_props(
                    "100",
                    "1172 ",
                    "VALLEY",
                    "146102000067",
                    PREFIX="",
                    STREETTYPE="LN",
                    SUFFIX=None,
                    UNITTYPE="APT",
                    UNIT="2",
                    CITY="UNINCORPORATED",
                    ZIPCODE="80302",
                ),
                0.0001,
                0.0001,
            ),
            point_feature(
                address_props("101", "2211", "PRATT", None, STREETTYPE="ST", UNIT="206", CITY="LONGMONT", ZIPCODE=" "),
                0.0002,
                0.0001,
            ),
        ]
    )

    assert (result.created, result.updated, result.skipped) == (2, 0, 0)
    rural, town = Address.objects.order_by("source_id")
    assert (rural.number, rural.street, rural.unit) == ("1172", "VALLEY LN", "APT 2")
    assert (rural.jurisdiction, rural.state, rural.zip_code) == ("UNINCORPORATED BOULDER COUNTY", "CO", "80302")
    assert (rural.county_fips, rural.county_apn) == ("08013", "146102000067")
    assert rural.geom.equals(Point(ORIGIN[0] + 0.0001, ORIGIN[1] + 0.0001, srid=STORAGE_SRID))
    assert (town.unit, town.zip_code) == ("#206", "")
    assert (town.county_fips, town.county_apn) == (None, None)


@pytest.mark.django_db
def test_unusable_address_points_are_skipped_and_recorded():
    result = boulder.load_addresses(
        [
            point_feature(address_props("1", "", "MAIN"), 0, 0),
            point_feature(address_props("2", "12", " "), 0, 0),
            point_feature(address_props(None, "12", "MAIN"), 0, 0),
            {"type": "Feature", "geometry": None, "properties": address_props("3", "12", "MAIN")},
            {"type": "Feature", "geometry": {"type": "Point"}, "properties": address_props("4", "12", "MAIN")},
        ]
    )

    assert (result.created, result.skipped) == (0, 5)
    rows = RejectedFeature.objects.all()
    assert {r.layer for r in rows} == {RejectedFeature.Layer.BOCO_ADDRESS_POINTS}
    assert {r.source_id: r.reason for r in rows} == {
        "1": RejectedFeature.Reason.NO_STREET_ADDRESS,
        "2": RejectedFeature.Reason.NO_STREET_ADDRESS,
        None: RejectedFeature.Reason.MISSING_ID,
        "3": RejectedFeature.Reason.NOT_A_POINT,
        "4": RejectedFeature.Reason.UNREADABLE_GEOMETRY,
    }


def test_points_are_stored_2d():
    point = point_from_geojson({"type": "Point", "coordinates": [-105.4, 40.05, 1650.0]})

    assert point is not None
    assert not point.hasz
    assert (point.x, point.y, point.srid) == (-105.4, 40.05, STORAGE_SRID)


@pytest.mark.django_db
def test_reloading_addresses_updates_in_place():
    boulder.load_addresses([point_feature(address_props("1", "12", "MAIN", STREETTYPE="ST"), 0, 0)])
    first = Address.objects.get()

    result = boulder.load_addresses([point_feature(address_props("1", "14", "MAIN", STREETTYPE="ST"), 0.0001, 0)])

    assert (result.created, result.updated) == (0, 1)
    first.refresh_from_db()
    assert first.number == "14"
    assert first.geom.x == pytest.approx(ORIGIN[0] + 0.0001)


# Retirement

JAN_1, FEB_1, MAR_1 = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)


def active(address_id: str, number: str = "12") -> dict:
    return point_feature(address_props(address_id, number, "MAIN", STATUS="ACTIVE"), 0, 0)


def retired(address_id: str) -> dict:
    # The county's retired points carry their old details; only the ID and status matter here.
    return point_feature(address_props(address_id, "99", "ELSEWHERE", STATUS="RETIRED"), 0.01, 0.01)


def tracked() -> dict[str | None, tuple[date, date | None]]:
    return {a.source_id: (a.tracked_from, a.tracked_to) for a in Address.objects.all()}


@pytest.mark.django_db
def test_reloading_unchanged_addresses_writes_nothing():
    features = [point_feature(address_props("1", "12", "MAIN", "A", STREETTYPE="ST", CITY="LONGMONT"), 0.0001, 0)]
    boulder.load_addresses(features)

    result = boulder.load_addresses(features)

    assert (result.created, result.updated, result.unchanged) == (0, 0, 1)
    assert "0 updated, 1 unchanged" in str(result)


@pytest.mark.django_db
def test_an_unchanged_address_that_comes_back_is_still_updated():
    boulder.load_addresses([active("1")], as_of=JAN_1)
    boulder.load_addresses([retired("1")], as_of=FEB_1)

    result = boulder.load_addresses([active("1")], as_of=MAR_1)

    assert (result.updated, result.unchanged) == (1, 0)
    assert tracked() == {"1": (JAN_1, None)}


@pytest.mark.django_db
def test_new_addresses_are_tracked_from_the_load_date():
    boulder.load_addresses([active("1")], as_of=JAN_1)

    assert tracked() == {"1": (JAN_1, None)}


@pytest.mark.django_db
def test_addresses_the_county_retires_are_kept_with_their_last_details():
    boulder.load_addresses([active("1"), active("2")], as_of=JAN_1)

    result = boulder.load_addresses([retired("1"), active("2")], as_of=FEB_1)

    assert result.retired == 1
    assert tracked() == {"1": (JAN_1, FEB_1), "2": (JAN_1, None)}
    gone = Address.objects.get(source_id="1")
    assert (gone.number, gone.street) == ("12", "MAIN")
    assert list(Address.objects.current().values_list("source_id", flat=True)) == ["2"]
    # Seeing it retired again doesn't move the date.
    assert boulder.load_addresses([retired("1")], as_of=MAR_1).retired == 0
    assert tracked()["1"] == (JAN_1, FEB_1)


@pytest.mark.django_db
def test_retired_addresses_never_loaded_are_ignored():
    result = boulder.load_addresses([retired("1")], as_of=JAN_1)

    assert (result.created, result.retired) == (0, 0)
    assert not Address.objects.exists()


@pytest.mark.django_db
def test_a_complete_load_retires_addresses_missing_from_it():
    boulder.load_addresses([active("1"), active("2"), active("3")], as_of=JAN_1)

    # 2 is gone from the layer; 3 is still there but its point is unreadable this time.
    unreadable = {"type": "Feature", "geometry": {"type": "Point"}, "properties": address_props("3", "12", "MAIN")}
    result = boulder.load_addresses([active("1"), unreadable], as_of=FEB_1, complete=True)

    assert (result.unchanged, result.retired, result.skipped) == (1, 1, 1)
    assert tracked() == {"1": (JAN_1, None), "2": (JAN_1, FEB_1), "3": (JAN_1, None)}


@pytest.mark.django_db
def test_a_partial_load_leaves_missing_addresses_alone():
    boulder.load_addresses([active("1"), active("2")], as_of=JAN_1)

    result = boulder.load_addresses([active("1")], as_of=FEB_1)

    assert result.retired == 0
    assert tracked() == {"1": (JAN_1, None), "2": (JAN_1, None)}


@pytest.mark.django_db
def test_an_address_that_comes_back_is_current_again():
    boulder.load_addresses([active("1")], as_of=JAN_1)
    boulder.load_addresses([], as_of=FEB_1, complete=True)

    result = boulder.load_addresses([active("1", number="14")], as_of=MAR_1, complete=True)

    assert (result.created, result.updated, result.retired) == (0, 1, 0)
    assert tracked() == {"1": (JAN_1, None)}
    assert Address.objects.get().number == "14"


# Linking to tracts


@pytest.fixture
def lots():
    """Lots A and B side by side, and two condo parcels C1 and C2 stacked on one outline east of them."""
    boulder.load_tracts(
        [
            feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001)),
            feature({"PARCEL_NO": "B"}, box(0.001, 0, 0.002, 0.001)),
            feature({"PARCEL_NO": "C1"}, box(0.003, 0, 0.004, 0.001)),
            feature({"PARCEL_NO": "C2"}, box(0.003, 0, 0.004, 0.001)),
        ]
    )
    return dict(TractIdentifier.objects.values_list("value", "tract_id"))


def tract_of() -> dict[str, int | None]:
    return dict(Address.objects.values_list("source_id", "tract_id"))


@pytest.mark.django_db
def test_addresses_link_to_the_tract_carrying_their_parcel_number(lots):
    boulder.load_addresses(
        [
            point_feature(address_props("on-a", "1", "MAIN", "A"), 0.0005, 0.0005),
            # A driveway point on B for a house on A: the parcel number wins.
            point_feature(address_props("driveway", "2", "MAIN", "A"), 0.0015, 0.0005),
            point_feature(address_props("condo", "3", "MAIN", "C2"), 0.0035, 0.0005),
        ]
    )

    changed = boulder.link_address_tracts()

    assert tract_of() == {"on-a": lots["A"], "driveway": lots["A"], "condo": lots["C2"]}
    assert changed == 3
    assert boulder.link_address_tracts() == 0


@pytest.mark.django_db
def test_addresses_without_a_known_parcel_number_fall_back_to_location(lots):
    boulder.load_addresses(
        [
            # Replatted: the county's address still carries a retired parcel number.
            point_feature(address_props("stale", "1", "MAIN", "OLD"), 0.0015, 0.0005),
            point_feature(address_props("no-apn", "2", "MAIN"), 0.0005, 0.0005),
            # Stacked parcels under the point and no number to choose between them.
            point_feature(address_props("stacked", "3", "MAIN", "OLD"), 0.0035, 0.0005),
            point_feature(address_props("nowhere", "4", "MAIN", "OLD"), 0.01, 0.01),
        ]
    )

    boulder.link_address_tracts()

    assert tract_of() == {"stale": lots["B"], "no-apn": lots["A"], "stacked": None, "nowhere": None}


@pytest.mark.django_db
def test_address_links_follow_parcel_numbers_loaded_later():
    boulder.load_addresses([point_feature(address_props("1", "1", "MAIN", "A"), 0.0005, 0.0005)])
    boulder.link_address_tracts()
    assert tract_of() == {"1": None}

    boulder.load_tracts([feature({"PARCEL_NO": "A"}, box(0, 0, 0.001, 0.001))])
    boulder.link_address_tracts()

    assert tract_of() == {"1": TractIdentifier.objects.get().tract_id}


@pytest.mark.django_db
def test_retired_addresses_keep_their_last_tract(lots):
    boulder.load_addresses([point_feature(address_props("1", "1", "MAIN", "A"), 0.0005, 0.0005)])
    boulder.link_address_tracts()
    boulder.load_addresses([], complete=True)

    # Parcel number A moves to lot B, which a current address carrying it would follow.
    TractIdentifier.objects.filter(value="A").update(value="A-OLD")
    TractIdentifier.objects.filter(value="B").update(value="A")
    assert boulder.link_address_tracts() == 0

    assert tract_of() == {"1": lots["A"]}
