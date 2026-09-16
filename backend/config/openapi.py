from __future__ import annotations


def _ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def _response(name: str | None = None, description: str = "OK") -> dict:
    value = {"description": description}
    if name:
        value["content"] = {"application/json": {"schema": _ref(name)}}
    return value


def _path_parameter(name: str) -> dict:
    return {
        "name": name,
        "in": "path",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }


def _operation(
    operation_id: str,
    *,
    response: str | None = None,
    request: str | None = None,
    parameters: list[dict] | None = None,
    status: str = "200",
    security: bool = True,
) -> dict:
    value = {
        "operationId": operation_id,
        "responses": {
            status: _response(response),
            "400": _response("ApiError", "Invalid request"),
            "401": _response("ApiError", "Authentication required"),
            "409": _response("ApiError", "Conflict"),
        },
    }
    if security:
        value["security"] = [{"cookieAuth": []}]
    if request:
        value["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": _ref(request)}},
        }
    if parameters:
        value["parameters"] = parameters
    return value


def _page_schema(item: str) -> dict:
    return {
        "type": "object",
        "required": ["items", "total", "page", "page_size"],
        "properties": {
            "items": {"type": "array", "items": _ref(item)},
            "total": {"type": "integer", "minimum": 0},
            "page": {"type": "integer", "minimum": 1},
            "page_size": {"type": "integer", "minimum": 1, "maximum": 100},
        },
    }


def inject_contract(result: dict, generator, request, public) -> dict:
    components = result.setdefault("components", {})
    components.setdefault("securitySchemes", {})["cookieAuth"] = {
        "type": "apiKey",
        "in": "cookie",
        "name": "__Host-xray_session",
    }
    schemas = components.setdefault("schemas", {})
    schemas.update(
        {
            "ApiError": {
                "type": "object",
                "required": ["code", "message", "retryable"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "retryable": {"type": "boolean"},
                    "operation_id": {"type": "string", "format": "uuid", "nullable": True},
                    "details": {"type": "object", "additionalProperties": True},
                },
            },
            "AdminSession": {
                "type": "object",
                "required": ["authenticated", "mfa_required"],
                "properties": {
                    "authenticated": {"type": "boolean"},
                    "mfa_required": {"type": "boolean"},
                    "admin": {
                        "type": "object",
                        "properties": {"username": {"type": "string"}},
                    },
                    "expires_at": {"type": "string", "format": "date-time", "nullable": True},
                    "recent_auth_until": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                    },
                },
            },
            "LoginRequest": {
                "type": "object",
                "required": ["username", "password"],
                "properties": {
                    "username": {"type": "string"},
                    "password": {"type": "string", "format": "password", "writeOnly": True},
                },
            },
            "LoginChallenge": {
                "type": "object",
                "required": ["challenge_id", "mfa_required", "totp_setup_required"],
                "properties": {
                    "challenge_id": {"type": "string", "format": "uuid"},
                    "mfa_required": {"type": "boolean"},
                    "totp_setup_required": {"type": "boolean"},
                    "expires_at": {"type": "string", "format": "date-time"},
                },
            },
            "CloudAccount": {
                "type": "object",
                "required": ["id", "name", "provider", "credential_version", "enabled"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "provider": {"type": "string", "enum": ["aws_lightsail", "aliyun_swas"]},
                    "external_account_id": {"type": "string"},
                    "credential_version": {"type": "integer"},
                    "enabled": {"type": "boolean"},
                    "validated_at": {"type": "string", "format": "date-time", "nullable": True},
                    "last_validation_code": {"type": "string"},
                },
            },
            "NodePool": {
                "type": "object",
                "required": ["id", "name", "quota", "used", "available", "allow_create"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "quota": {"type": "integer"},
                    "used": {"type": "integer"},
                    "available": {"type": "integer"},
                    "allow_create": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "ManagedNode": {
                "type": "object",
                "required": [
                    "id",
                    "name",
                    "pool_id",
                    "provider",
                    "region",
                    "provisioning_state",
                    "health_state",
                    "security_state",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "pool_id": {"type": "string", "format": "uuid"},
                    "pool_name": {"type": "string"},
                    "cloud_account_id": {"type": "string", "format": "uuid"},
                    "cloud_account_name": {"type": "string"},
                    "provider": {"type": "string"},
                    "region": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "image_id": {"type": "string"},
                    "external_id": {"type": "string"},
                    "addresses": {"type": "array", "items": {"type": "object"}},
                    "raw_cloud_state": {"type": "string"},
                    "desired_state": {"type": "string"},
                    "provisioning_state": {"type": "string"},
                    "health_state": {"type": "string"},
                    "security_state": {"type": "string"},
                    "consumes_quota": {"type": "boolean"},
                    "desired_generation": {"type": "integer"},
                    "applied_generation": {"type": "integer"},
                    "observed_at": {"type": "string", "format": "date-time", "nullable": True},
                    "observation_error": {"type": "string"},
                    "last_error_code": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "OperationStep": {
                "type": "object",
                "required": ["name", "phase", "status", "attempt"],
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "phase": {"type": "string"},
                    "status": {"type": "string"},
                    "attempt": {"type": "integer"},
                    "external_request_id": {"type": "string"},
                    "result": {"type": "object", "additionalProperties": True},
                    "evidence": {"type": "object", "additionalProperties": True},
                    "started_at": {"type": "string", "format": "date-time", "nullable": True},
                    "finished_at": {"type": "string", "format": "date-time", "nullable": True},
                },
            },
            "Operation": {
                "type": "object",
                "required": [
                    "id",
                    "kind",
                    "target_type",
                    "target_id",
                    "status",
                    "current_step",
                    "can_cancel",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "kind": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string", "format": "uuid"},
                    "status": {"type": "string"},
                    "current_step": {"type": "string"},
                    "can_cancel": {"type": "boolean"},
                    "error_code": {"type": "string"},
                    "error_details": {"type": "object", "additionalProperties": True},
                    "result": {"type": "object", "additionalProperties": True},
                    "steps": {"type": "array", "items": _ref("OperationStep")},
                    "revocation_nodes": {"type": "array", "items": {"type": "object"}},
                    "link_revoked": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "AccessProfile": {
                "type": "object",
                "required": ["id", "name", "status", "publishing_frozen"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "status": {"type": "string"},
                    "publishing_frozen": {"type": "boolean"},
                    "credential_count": {"type": "integer"},
                    "subscription_id": {"type": "string", "format": "uuid", "nullable": True},
                    "subscription_status": {"type": "string", "nullable": True},
                    "revoked_at": {"type": "string", "format": "date-time", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "Subscription": {
                "type": "object",
                "required": ["id", "profile_id", "profile_name", "status", "token_epoch"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "profile_id": {"type": "string", "format": "uuid"},
                    "profile_name": {"type": "string"},
                    "profile_status": {"type": "string"},
                    "status": {"type": "string"},
                    "token_epoch": {"type": "integer"},
                    "current_revision": {"type": "integer", "nullable": True},
                    "public_version": {"type": "string", "nullable": True},
                    "revision_usable": {"type": "boolean"},
                    "formats": {"type": "array", "items": {"type": "string"}},
                    "unavailable_reasons": {"type": "object", "additionalProperties": True},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "AuditEvent": {
                "type": "object",
                "required": ["id", "action", "target_type", "result", "created_at"],
                "properties": {
                    "id": {"type": "integer"},
                    "action": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string"},
                    "result": {"type": "string"},
                    "metadata": {"type": "object", "additionalProperties": True},
                    "actor": {"type": "string", "nullable": True},
                    "request_id": {"type": "string"},
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
            "Overview": {
                "type": "object",
                "properties": {
                    "counts": {"type": "object", "additionalProperties": {"type": "integer"}},
                    "security_mode": {"type": "string"},
                    "recent_operations": {"type": "array", "items": {"type": "object"}},
                    "recent_audit": {"type": "array", "items": {"type": "object"}},
                },
            },
            "SystemInfo": {
                "type": "object",
                "properties": {
                    "version": {"type": "string"},
                    "environment": {"type": "string"},
                    "debug": {"type": "boolean"},
                    "allowed_hosts": {"type": "array", "items": {"type": "string"}},
                    "csrf_trusted_origins": {"type": "array", "items": {"type": "string"}},
                },
            },
            "ActionPreview": {
                "type": "object",
                "required": ["id", "kind", "target_id", "required_phrase", "expires_at"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "kind": {"type": "string"},
                    "target_id": {"type": "string", "format": "uuid"},
                    "snapshot": {"type": "object", "additionalProperties": True},
                    "required_phrase": {"type": "string"},
                    "expires_at": {"type": "string", "format": "date-time"},
                },
            },
            "SecretDelivery": {
                "type": "object",
                "required": ["subscription_id", "token", "urls", "display_once"],
                "properties": {
                    "subscription_id": {"type": "string", "format": "uuid"},
                    "token": {"type": "string", "writeOnly": True},
                    "urls": {"type": "object", "additionalProperties": {"type": "string"}},
                    "display_once": {"type": "boolean"},
                },
            },
            "GenericObject": {"type": "object", "additionalProperties": True},
            "PaginatedCloudAccountList": _page_schema("CloudAccount"),
            "PaginatedNodePoolList": _page_schema("NodePool"),
            "PaginatedManagedNodeList": _page_schema("ManagedNode"),
            "PaginatedOperationList": _page_schema("Operation"),
            "PaginatedAccessProfileList": _page_schema("AccessProfile"),
            "PaginatedSubscriptionList": _page_schema("Subscription"),
            "PaginatedAuditEventList": _page_schema("AuditEvent"),
        }
    )

    def uuid(name: str) -> list[dict]:
        return [_path_parameter(name)]

    paths = {
        "/api/v1/auth/session": {
            "get": _operation(
                "auth_session_retrieve", response="AdminSession", security=False
            )
        },
        "/api/v1/auth/login": {
            "post": _operation(
                "auth_login_create",
                response="LoginChallenge",
                request="LoginRequest",
                security=False,
            )
        },
        "/api/v1/cloud-accounts/": {
            "get": _operation("cloud_accounts_list", response="PaginatedCloudAccountList"),
            "post": _operation(
                "cloud_accounts_create",
                response="CloudAccount",
                request="GenericObject",
                status="201",
            ),
        },
        "/api/v1/node-pools/": {
            "get": _operation("node_pools_list", response="PaginatedNodePoolList"),
            "post": _operation(
                "node_pools_create", response="NodePool", request="GenericObject", status="201"
            ),
        },
        "/api/v1/node-pools/{pool_id}/": {
            "get": _operation(
                "node_pools_retrieve",
                response="NodePool",
                parameters=uuid("pool_id"),
            ),
            "patch": _operation(
                "node_pools_partial_update",
                response="NodePool",
                request="GenericObject",
                parameters=uuid("pool_id"),
            ),
        },
        "/api/v1/nodes/": {
            "get": _operation("nodes_list", response="PaginatedManagedNodeList"),
            "post": _operation(
                "nodes_create", response="GenericObject", request="GenericObject", status="202"
            ),
        },
        "/api/v1/nodes/{node_id}/": {
            "get": _operation("nodes_retrieve", response="ManagedNode", parameters=uuid("node_id"))
        },
        "/api/v1/operations/": {
            "get": _operation("operations_list", response="PaginatedOperationList")
        },
        "/api/v1/operations/previews/": {
            "post": _operation(
                "action_previews_create",
                response="ActionPreview",
                request="GenericObject",
                status="201",
            )
        },
        "/api/v1/operations/{operation_id}/": {
            "get": _operation(
                "operations_retrieve", response="Operation", parameters=uuid("operation_id")
            )
        },
        "/api/v1/operations/{operation_id}/cancel/": {
            "post": _operation(
                "operations_cancel_create",
                response="Operation",
                parameters=uuid("operation_id"),
                status="202",
            )
        },
        "/api/v1/operations/{operation_id}/retry/": {
            "post": _operation(
                "operations_retry_create",
                response="Operation",
                parameters=uuid("operation_id"),
                status="202",
            )
        },
        "/api/v1/access-profiles/": {
            "get": _operation("access_profiles_list", response="PaginatedAccessProfileList"),
            "post": _operation(
                "access_profiles_create",
                response="AccessProfile",
                request="GenericObject",
                status="201",
            ),
        },
        "/api/v1/access-profiles/{profile_id}/subscription/": {
            "post": _operation(
                "subscriptions_issue_create",
                response="SecretDelivery",
                parameters=uuid("profile_id"),
                status="201",
            )
        },
        "/api/v1/access-profiles/{profile_id}/force-revoke/": {
            "post": _operation(
                "subscriptions_force_revoke_create",
                response="GenericObject",
                request="GenericObject",
                parameters=uuid("profile_id"),
                status="202",
            )
        },
        "/api/v1/subscriptions/": {
            "get": _operation("subscriptions_list", response="PaginatedSubscriptionList")
        },
        "/api/v1/subscriptions/{subscription_id}/rotate/": {
            "post": _operation(
                "subscriptions_rotate_create",
                response="SecretDelivery",
                parameters=uuid("subscription_id"),
                status="201",
            )
        },
        "/api/v1/audit-events/": {
            "get": _operation("audit_events_list", response="PaginatedAuditEventList")
        },
        "/api/v1/overview": {"get": _operation("overview_retrieve", response="Overview")},
        "/api/v1/system": {"get": _operation("system_retrieve", response="SystemInfo")},
    }
    result.setdefault("paths", {}).update(paths)
    return result
