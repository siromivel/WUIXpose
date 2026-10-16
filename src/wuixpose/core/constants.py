"""Values shared across core: spatial reference systems, unit conversions, data credits.

A leaf module: it imports nothing from wuixpose, so models, services and views can all use it
without importing each other (test_layering.py enforces this).
"""

# Geometries are stored as longitude/latitude in degrees (SRID 4326, the GPS standard).
# A degree is not a fixed distance: it's ~364,000 ft north-south everywhere, but east-west
# it shrinks toward the poles (~280,000 ft in Colorado). So never buffer or measure
# directly on these geometries, e.g. geom.buffer(5) means 5 *degrees*, not 5 feet.
# For distances, first convert the geometry to a projected coordinate system that
# uses meters (geom.transform(<local UTM SRID>)), or cast to PostGIS `geography`,
# which measures in meters on the Earth's surface.
STORAGE_SRID = 4326
# Web Mercator, the projection vector tiles are drawn in.
WEB_MERCATOR_SRID = 3857
# NAD83 / CONUS Albers, an equal-area projection in meters, for measuring areas in the US.
EQUAL_AREA_SRID = 5070

M_PER_FT = 0.3048
SQ_M_PER_ACRE = 4046.8564224
SQ_FT_PER_SQ_M = 10.763910417

# Rows per statement for bulk_create and bulk_update.
DB_BATCH_SIZE = 2000

# A structure belongs to the tract holding at least this share of its footprint. Lot lines and
# footprints are digitized separately, so a house wholly on one lot often pokes a few percent
# over the line; a footprint split more evenly than this has no single tract.
MIN_TRACT_SHARE = 0.9

# Credit required by CC BY 4.0 wherever Boulder County data is shown. HTML, as map clients render it.
BOULDER_COUNTY_ATTRIBUTION = (
    'Parcels, footprints and addresses: <a href="https://opendata-bouldercounty.hub.arcgis.com/">Boulder County</a>, '
    '<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>'
)
