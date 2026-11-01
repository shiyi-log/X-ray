from __future__ import annotations

import hashlib
import json
from uuid import UUID

from django.db import transaction
from django.http import JsonResponse

from apps.identity.models import SuperAdmin
from apps.nodes.models import NodeProtocol
from common.admin_api import admin_endpoint, json_payload, paginated_response
from common.errors import DomainError

from .models import Subscription, SubscriptionMutation, SubscriptionPlan
from .policy import positive_integer
from .serializers import profile_representation


def mutation(request, scope, payload, action):
    try:
        key = UUID(request.headers.get("Idempotency-Key", ""))
    except (ValueError, TypeError):
        raise ValueError("Idempotency-Key must be a UUID") from None
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with transaction.atomic():
        SuperAdmin.objects.select_for_update().get(pk=request.xray_admin.pk)
        existing = SubscriptionMutation.objects.filter(pk=key).first()
        if existing:
            if existing.scope != scope or existing.request_hash != digest:
                raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键的请求不一致", status_code=409)
            return existing.result
        result = action()
        from apps.audit.services import AuditService

        AuditService.append(
            action="subscription.management.mutate",
            target_type="subscription",
            target_id=scope,
            result="SUCCEEDED",
            metadata={"scope": scope},
            actor=request.xray_admin,
        )
        SubscriptionMutation.objects.create(
            key=key, scope=scope, request_hash=digest, result=result
        )
        return result


def plan_representation(plan):
    return {
        "id": str(plan.pk),
        "name": plan.name,
        "traffic_limit_bytes": plan.traffic_limit_bytes,
        "duration_days": plan.duration_days,
        "enabled": plan.enabled,
    }


@admin_endpoint("GET", "POST", "PATCH")
def plans(request, plan_id=None):
    if request.method == "GET":
        return paginated_response(
            request, SubscriptionPlan.objects.order_by("name"), plan_representation
        )
    payload = json_payload(request)

    def save():
        if set(payload) - {"name", "traffic_limit_bytes", "duration_days", "enabled"}:
            raise ValueError("unsupported plan fields")
        plan = (
            SubscriptionPlan.objects.select_for_update().get(pk=plan_id)
            if plan_id
            else SubscriptionPlan()
        )
        if "name" in payload:
            plan.name = str(payload["name"]).strip()
        if not plan.name or len(plan.name) > 120:
            raise ValueError("name must contain 1 to 120 characters")
        for field in ("traffic_limit_bytes", "duration_days"):
            if field in payload:
                value = positive_integer(payload[field], field)
                if field == "duration_days" and value is not None and value > 36500:
                    raise ValueError("duration_days must not exceed 36500")
                setattr(plan, field, value)
        if "enabled" in payload:
            if not isinstance(payload["enabled"], bool):
                raise ValueError("enabled must be a boolean")
            plan.enabled = payload["enabled"]
        plan.save()
        return plan_representation(plan)

    return JsonResponse(
        mutation(request, f"plan:{plan_id or 'create'}", payload, save),
        status=200 if plan_id else 201,
    )


@admin_endpoint("GET", "POST")
def catalog(request):
    if request.method == "POST":
        payload = json_payload(request)

        def create():
            from apps.nodes.models import ManagedNode
            from apps.nodes.protocols import default_transport, validate_protocol_config

            allowed = {
                "node_id",
                "protocol",
                "port",
                "transport",
                "tls_enabled",
                "server_name",
                "certificate_ref",
            }
            if set(payload) - allowed:
                raise ValueError("unsupported protocol fields")
            node = ManagedNode.objects.get(
                pk=payload.get("node_id"), desired_state="PRESENT", security_state="OPEN"
            )
            name = payload.get("protocol")
            transport = payload.get("transport", default_transport(name))
            validate_protocol_config(name, {"transport": transport})
            port = positive_integer(payload.get("port"), "port", nullable=False)
            if (
                port > 65535
                or port == 10085
                or NodeProtocol.objects.filter(node=node, port=port, enabled=True).exists()
            ):
                raise ValueError("port is unavailable")
            tls = payload.get("tls_enabled", False)
            if not isinstance(tls, bool):
                raise ValueError("tls_enabled must be boolean")
            if name == "trojan" and not tls:
                raise ValueError("Trojan requires TLS")
            certificate = str(payload.get("certificate_ref") or "")
            server_name = str(payload.get("server_name") or "")
            if tls and (
                not certificate.startswith("/usr/local/etc/xray/certs/")
                or ".." in certificate.split("/")
                or not server_name
            ):
                raise ValueError("TLS requires server name and managed certificate path")
            protocol = NodeProtocol.objects.create(
                node=node,
                protocol=name,
                port=port,
                transport=transport,
                tls_enabled=tls,
                server_name=server_name,
                certificate_ref=certificate,
                method="aes-128-gcm" if name == "shadowsocks" else "",
            )
            return {"id": str(protocol.pk)}

        return JsonResponse(mutation(request, "protocol:create", payload, create), status=201)
    values = (
        NodeProtocol.objects.select_related("node")
        .filter(
            enabled=True,
            credential_scope="profile",
            node__desired_state="PRESENT",
            node__security_state="OPEN",
        )
        .order_by("node_id", "port")
    )
    return JsonResponse(
        {
            "items": [
                {
                    "id": str(p.pk),
                    "node_id": str(p.node_id),
                    "name": p.node.external_id or p.node.deterministic_name,
                    "protocol": p.protocol,
                    "port": p.port,
                    "transport": p.transport,
                    "tls": p.tls_enabled,
                    "state": p.node.provisioning_state,
                    "publishable_tls": p.protocol != "trojan"
                    or bool(p.tls_enabled and p.server_name),
                }
                for p in values
            ]
        }
    )


@admin_endpoint("GET")
def subscription_detail(request, subscription_id):
    from .models import NodeCredential
    from .serializers import subscription_representation

    subscription = Subscription.objects.select_related(
        "pool", "profile", "current_revision"
    ).get(pk=subscription_id)
    value = subscription_representation(subscription)
    value["profile"] = profile_representation(subscription.profile)
    latest = {}
    for credential in (
        NodeCredential.objects.filter(profile=subscription.profile, revoked_at__isnull=True)
        .select_related("node", "protocol")
        .order_by("version")
    ):
        latest[credential.protocol_id] = credential
    value["assignments"] = [
        {
            "id": str(c.pk),
            "protocol_id": str(c.protocol_id),
            "node_id": str(c.node_id),
            "protocol": c.protocol.protocol,
            "desired_generation": c.desired_generation,
            "applied_generation": c.applied_generation,
            "ready": c.desired_generation == c.applied_generation == c.node.applied_generation
            and c.node.desired_generation == c.node.applied_generation,
        }
        for c in latest.values()
    ]
    value["revisions"] = [
        {
            "number": r.number,
            "usable": r.usable,
            "published_at": r.published_at.isoformat(),
            "formats": sorted(r.payloads),
        }
        for r in subscription.revisions.order_by("-number")[:20]
    ]
    return JsonResponse(value)


@admin_endpoint("POST", recent=True)
def assign(request, subscription_id):
    from .access import AccessService

    payload = json_payload(request)
    ids = payload.get("protocol_ids")
    if ids is not None:
        if not isinstance(ids, list) or len(ids) > 100:
            raise ValueError("protocol_ids must be an array of at most 100 UUIDs")
        try:
            ids = [UUID(str(value)) for value in ids]
        except (ValueError, TypeError):
            raise ValueError("invalid protocol UUID") from None
        if len(ids) != len(set(ids)):
            raise ValueError("protocol_ids must be unique")

    def save():
        subscription = Subscription.objects.select_for_update().get(pk=subscription_id)
        operations = AccessService.assign(
            subscription.profile_id, protocol_ids=ids, admin=request.xray_admin
        )
        return {"operation_ids": [str(o.pk) for o in operations], "pending": bool(operations)}

    return JsonResponse(mutation(request, f"assign:{subscription_id}", payload, save), status=202)
