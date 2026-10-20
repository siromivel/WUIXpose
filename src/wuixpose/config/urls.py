from django.contrib import admin
from django.urls import include, path

from wuixpose.core import api, tiles
from wuixpose.core.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health/", health, name="health"),
    path("api/config/", api.config, name="config"),
    path("api/summary/", api.summary, name="summary"),
    path("api/tracts/<int:pk>/", api.tract_detail, name="tract-detail"),
    path("api/structures/<int:pk>/", api.structure_detail, name="structure-detail"),
    path("api/search/", api.search, name="search"),
    # allauth's JSON API for the map UI (browser/v1/...), and the callbacks OIDC providers redirect
    # back to (oidc/<provider id>/login/callback/). Under /api so the dev proxy covers them.
    path("api/auth/", include("allauth.headless.urls")),
    path("api/auth/", include("allauth.urls")),
    path("tiles/<str:layer>.json", tiles.tilejson, name="tilejson"),
    path("tiles/<str:layer>/<int:z>/<int:x>/<int:y>.mvt", tiles.tile, name="tile"),
]
