from django.urls import include, path

from apps.identity.views import system
from common.health import liveness, readiness

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("health/ready", readiness, name="health-ready"),
    path("api/v1/auth/", include("apps.identity.urls")),
    path("api/v1/cloud-accounts/", include("apps.cloud_accounts.urls")),
    path("api/v1/system", system, name="system"),
    path("", include("apps.subscriptions.urls")),
]
