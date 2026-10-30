from django.http import JsonResponse

from apps.audit.models import AuditEvent
from apps.cloud_accounts.models import CloudAccount
from apps.nodes.models import ManagedNode
from apps.operations.models import Operation
from apps.subscriptions.models import AccessProfile, SecurityState, Subscription
from common.admin_api import admin_endpoint


@admin_endpoint("GET")
def overview(request):
    state = SecurityState.objects.filter(singleton_key=1).first()
    return JsonResponse(
        {
            "counts": {
                "cloud_accounts": CloudAccount.objects.count(),
                "nodes": ManagedNode.objects.count(),
                "operations_active": Operation.objects.exclude(
                    status__in=Operation.TERMINAL_STATUSES
                ).count(),
                "access_profiles": AccessProfile.objects.count(),
                "subscriptions": Subscription.objects.count(),
            },
            "security_mode": state.mode if state else "MAINTENANCE",
            "recent_operations": [
                {
                    "id": str(value.pk),
                    "kind": value.kind,
                    "status": value.status,
                    "updated_at": value.updated_at.isoformat(),
                }
                for value in Operation.objects.order_by("-updated_at")[:5]
            ],
            "recent_audit": [
                {
                    "id": value.pk,
                    "action": value.action,
                    "result": value.result,
                    "created_at": value.created_at.isoformat(),
                }
                for value in AuditEvent.objects.order_by("-created_at")[:5]
            ],
        }
    )
