from django.contrib import admin
from django.urls import path

from wuixpose.core.views import health

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health, name="health")
]
