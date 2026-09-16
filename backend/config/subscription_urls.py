from django.urls import include, path

from common.health import liveness, readiness

urlpatterns = [
    path("health/live", liveness, name="subscription-health-live"),
    path("health/ready", readiness, name="subscription-health-ready"),
    path("", include("apps.subscriptions.urls")),
]
