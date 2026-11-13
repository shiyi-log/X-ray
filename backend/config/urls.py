from django.urls import include, path

from apps.identity.views import system
from apps.nodes.urls import node_urlpatterns, pool_urlpatterns
from apps.subscriptions.admin_urls import (
    profile_urlpatterns,
    subscription_urlpatterns,
)
from common.health import liveness, readiness

from .admin_views import overview

urlpatterns = [
    path("health/live", liveness, name="health-live"),
    path("health/ready", readiness, name="health-ready"),
    path("api/v1/auth/", include("apps.identity.urls")),
    path("api/v1/cloud-accounts/", include("apps.cloud_accounts.urls")),
    path("api/v1/node-pools/", include(pool_urlpatterns)),
    path("api/v1/nodes/", include(node_urlpatterns)),
    path("api/v1/operations/", include("apps.operations.urls")),
    path(
        "api/v1/access-profiles/",
        include(profile_urlpatterns),
    ),
    path(
        "api/v1/subscriptions/",
        include(subscription_urlpatterns),
    ),
    path("api/v1/audit-events/", include("apps.audit.urls")),
    path("api/v1/overview", overview, name="overview"),
    path("api/v1/system", system, name="system"),
    path("api/v1/system/upgrade/", include("apps.identity.upgrade_urls")),
    path("", include("apps.subscriptions.urls")),
]
