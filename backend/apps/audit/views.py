from common.admin_api import admin_endpoint, paginated_response

from .models import AuditEvent


def representation(event: AuditEvent) -> dict:
    return {
        "id": event.pk,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "result": event.result,
        "metadata": event.metadata,
        "actor": event.actor.username if event.actor else None,
        "request_id": event.request_id,
        "created_at": event.created_at.isoformat(),
    }


@admin_endpoint("GET")
def collection(request):
    values = AuditEvent.objects.select_related("actor").order_by("-created_at", "-pk")
    if request.GET.get("result"):
        values = values.filter(result=request.GET["result"])
    return paginated_response(request, values, representation)
