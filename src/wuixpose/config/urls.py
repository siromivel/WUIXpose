from django.contrib import admin
from django.urls import path

from wuixpose.core import api, tiles
from wuixpose.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/summary/", api.summary, name="summary"),
    path("api/tracts/<int:pk>/", api.tract_detail, name="tract-detail"),
    path("api/structures/<int:pk>/", api.structure_detail, name="structure-detail"),
    path("tiles/<str:layer>/<int:z>/<int:x>/<int:y>.mvt", tiles.tile, name="tile"),
]
