from django.urls import include, path
from common.health import liveness, readiness
from apps.identity.views import system

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("health/ready", readiness, name="health-ready"),
    path("api/v1/auth/", include("apps.identity.urls")),
    path("api/v1/system", system, name="system"),
]
