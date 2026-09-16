from django.urls import path
from common.health import liveness, readiness

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("health/ready", readiness, name="health-ready"),
]
