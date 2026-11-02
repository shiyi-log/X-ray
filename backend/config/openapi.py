from __future__ import annotations

from common.regions import SUPPORTED_REGIONS


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
    extra_responses: dict[str, dict] | None = None,
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
    if extra_responses:
        value["responses"].update(extra_responses)
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
            "LocalLoginCapability": {
                "type": "object",
                "required": ["enabled"],
                "properties": {"enabled": {"type": "boolean"}},
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
            "CloudAccountPatch": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
                "minProperties": 1,
            },
            "NodePool": {
                "type": "object",
                "required": [
                    "id",
                    "name",
                    "region",
                    "regions",
                    "allocations",
                    "quota",
                    "used",
                    "available",
                    "allow_create",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "region": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                    "regions": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                    },
                    "allocations": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["region", "quota", "used", "available"],
                            "properties": {
                                "region": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                                "quota": {"type": "integer", "minimum": 0},
                                "used": {"type": "integer", "minimum": 0},
                                "available": {"type": "integer", "minimum": 0},
                            },
                        },
                    },
                    "quota": {"type": "integer"},
                    "used": {"type": "integer"},
                    "available": {"type": "integer"},
                    "allow_create": {"type": "boolean"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "NodePoolAllocationInput": {
                "type": "object",
                "required": ["region", "quota"],
                "additionalProperties": False,
                "properties": {
                    "region": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                    "quota": {"type": "integer", "minimum": 0},
                },
            },
            "NodePoolWriteRequest": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "allocations": {
                        "type": "array",
                        "minItems": 1,
                        "items": _ref("NodePoolAllocationInput"),
                    },
                    "region": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                    "quota": {"type": "integer", "minimum": 1},
                    "allow_create": {"type": "boolean"},
                },
                "anyOf": [
                    {"required": ["allocations"]},
                    {"required": ["region"]},
                    {"required": ["quota"]},
                ],
            },
            "NodeCreateRequest": {
                "type": "object",
                "required": ["account_id", "plan_id", "image_id"],
                "additionalProperties": False,
                "properties": {
                    "account_id": {"type": "string", "format": "uuid"},
                    "region": {"type": "string", "enum": list(SUPPORTED_REGIONS)},
                    "plan_id": {"type": "string"},
                    "image_id": {"type": "string"},
                },
            },
            "NodeActionRequest": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "preview_id": {"type": "string", "format": "uuid"},
                    "confirmation": {"type": "string"},
                },
            },
            "OperationAccepted": {
                "type": "object",
                "required": ["operation_id", "status", "target_type", "target_id"],
                "properties": {
                    "operation_id": {"type": "string", "format": "uuid"},
                    "status": {"type": "string"},
                    "target_type": {"type": "string"},
                    "target_id": {"type": "string", "format": "uuid"},
                },
            },
            "ManagedNode": {
                "type": "object",
                "required": [
                    "id",
                    "name",
                    "provider",
                    "region",
                    "provisioning_state",
                    "health_state",
                    "security_state",
                    "traffic_upload_bytes",
                    "traffic_download_bytes",
                    "traffic_total_bytes",
                    "traffic_state",
                    "metering_coverage",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "cloud_account_id": {"type": "string", "format": "uuid"},
                    "cloud_account_name": {"type": "string"},
                    "provider": {"type": "string"},
                    "region": {"type": "string"},
                    "plan_id": {"type": "string"},
                    "image_id": {"type": "string"},
                    "external_id": {"type": "string"},
                    "addresses": {"type": "array", "items": {"type": "object"}},
                    "traffic_upload_bytes": {"type": "integer", "minimum": 0},
                    "traffic_download_bytes": {"type": "integer", "minimum": 0},
                    "traffic_total_bytes": {"type": "integer", "minimum": 0},
                    "traffic_sampled_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                    },
                    "traffic_state": {"type": "string", "enum": ["COLLECTED", "NO_DATA"]},
                    "metering_coverage": {
                        "type": "string",
                        "enum": ["SUPPORTED", "PARTIAL"],
                    },
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
                "required": [
                    "id",
                    "pool_id",
                    "pool_name",
                    "profile_id",
                    "profile_name",
                    "status",
                    "current_token_status",
                    "token_epoch",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "pool_id": {"type": "string", "format": "uuid"},
                    "pool_name": {"type": "string"},
                    "profile_id": {"type": "string", "format": "uuid"},
                    "profile_name": {"type": "string"},
                    "profile_status": {"type": "string"},
                    "status": {"type": "string"},
                    "current_token_status": {
                        "type": "string",
                        "enum": ["ACTIVE", "REVOKED", "EXPIRED"],
                        "nullable": True,
                    },
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
            "SubscriptionToken": {
                "type": "object",
                "required": [
                    "id",
                    "subscription_id",
                    "token_epoch",
                    "status",
                    "is_current",
                    "created_at",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "subscription_id": {"type": "string", "format": "uuid"},
                    "token_epoch": {"type": "integer"},
                    "status": {"type": "string", "enum": ["ACTIVE", "REVOKED", "EXPIRED"]},
                    "is_current": {"type": "boolean"},
                    "revoked_at": {"type": "string", "format": "date-time", "nullable": True},
                    "replaced_by_id": {"type": "string", "format": "uuid", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
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
                    "provider_identity_network": _ref("ProviderIdentityNetworkSetting"),
                    "node_status_sync": _ref("NodeStatusSyncSetting"),
                },
            },
            "ProviderIdentityNetworkSetting": {
                "type": "object",
                "required": ["enabled", "source"],
                "properties": {
                    "enabled": {"type": "boolean"},
                    "source": {"type": "string", "enum": ["DATABASE", "ENVIRONMENT"]},
                },
            },
            "NodeStatusSyncSetting": {
                "type": "object",
                "required": [
                    "enabled",
                    "interval_minutes",
                    "last_scheduled_at",
                    "source",
                ],
                "properties": {
                    "enabled": {"type": "boolean"},
                    "interval_minutes": {"type": "integer", "minimum": 5, "maximum": 1440},
                    "last_scheduled_at": {
                        "type": "string",
                        "format": "date-time",
                        "nullable": True,
                    },
                    "source": {"type": "string", "enum": ["DATABASE", "DEFAULT"]},
                },
            },
            "SystemSettingsPatch": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "provider_identity_network_enabled": {"type": "boolean"},
                    "node_status_sync_enabled": {"type": "boolean"},
                    "node_status_sync_interval_minutes": {
                        "type": "integer", "minimum": 5, "maximum": 1440
                    },
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
                "required": ["subscription_id", "token", "url", "display_once"],
                "properties": {
                    "subscription_id": {"type": "string", "format": "uuid"},
                    "token": {"type": "string", "writeOnly": True},
                    "url": {"type": "string", "format": "uri"},
                    "display_once": {"type": "boolean"},
                },
            },
            "SubscriptionTokenRevokeRequest": {
                "type": "object",
                "required": ["preview_id", "confirmation"],
                "additionalProperties": False,
                "properties": {
                    "preview_id": {"type": "string", "format": "uuid"},
                    "confirmation": {"type": "string", "minLength": 1},
                },
            },
            "ActionPreviewRequest": {
                "type": "object",
                "required": ["kind", "target_id"],
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string"},
                    "target_id": {"type": "string", "format": "uuid"},
                    "params": {"type": "object", "additionalProperties": True},
                },
            },
            "SubscriptionTokenRevoke": {
                "type": "object",
                "required": [
                    "id",
                    "subscription_id",
                    "token_epoch",
                    "status",
                    "is_current",
                    "created_at",
                ],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "subscription_id": {"type": "string", "format": "uuid"},
                    "token_epoch": {"type": "integer"},
                    "status": {"type": "string", "enum": ["REVOKED"]},
                    "is_current": {"type": "boolean"},
                    "revoked_at": {"type": "string", "format": "date-time", "nullable": True},
                    "replaced_by_id": {"type": "string", "format": "uuid", "nullable": True},
                    "created_at": {"type": "string", "format": "date-time"},
                },
            },
            "GenericObject": {"type": "object", "additionalProperties": True},
            "PaginatedCloudAccountList": _page_schema("CloudAccount"),
            "PaginatedNodePoolList": _page_schema("NodePool"),
            "PaginatedManagedNodeList": _page_schema("ManagedNode"),
            "PaginatedOperationList": _page_schema("Operation"),
            "PaginatedAccessProfileList": _page_schema("AccessProfile"),
            "PaginatedSubscriptionList": _page_schema("Subscription"),
            "PaginatedSubscriptionTokenList": _page_schema("SubscriptionToken"),
            "PaginatedAuditEventList": _page_schema("AuditEvent"),
        }
    )

    def uuid(name: str) -> list[dict]:
        return [_path_parameter(name)]

    local_login_create = _operation(
        "auth_local_login_create", response="AdminSession", security=False
    )
    local_login_create["responses"]["404"] = _response(
        "ApiError", "Local test login is unavailable"
    )

    paths = {
        "/api/v1/auth/session": {
            "get": _operation("auth_session_retrieve", response="AdminSession", security=False)
        },
        "/api/v1/auth/local-login/status": {
            "get": _operation(
                "auth_local_login_status_retrieve",
                response="LocalLoginCapability",
                security=False,
            )
        },
        "/api/v1/auth/local-login": {"post": local_login_create},
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
        "/api/v1/cloud-accounts/{account_id}/": {
            "get": _operation(
                "cloud_accounts_retrieve",
                response="CloudAccount",
                parameters=uuid("account_id"),
            ),
            "patch": _operation(
                "cloud_accounts_partial_update",
                response="CloudAccount",
                request="CloudAccountPatch",
                parameters=uuid("account_id"),
            ),
        },
        "/api/v1/node-pools/": {
            "get": _operation("node_pools_list", response="PaginatedNodePoolList"),
            "post": _operation(
                "node_pools_create",
                response="NodePool",
                request="NodePoolWriteRequest",
                status="201",
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
                "nodes_create",
                response="OperationAccepted",
                request="NodeCreateRequest",
                status="202",
            ),
        },
        "/api/v1/nodes/{node_id}/": {
            "get": _operation("nodes_retrieve", response="ManagedNode", parameters=uuid("node_id"))
        },
        "/api/v1/nodes/{node_id}/refresh/": {
            "post": _operation(
                "node_refresh_create",
                response="OperationAccepted",
                request="GenericObject",
                parameters=uuid("node_id"),
                status="202",
            )
        },
        "/api/v1/nodes/{node_id}/actions/{action}/": {
            "post": _operation(
                "node_actions_create",
                response="OperationAccepted",
                request="NodeActionRequest",
                parameters=uuid("node_id")
                + [
                    {
                        "name": "action",
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "enum": [
                                "start",
                                "stop",
                                "reboot",
                                "delete",
                                "reinstall",
                                "quarantine",
                            ],
                        },
                    }
                ],
                status="202",
            )
        },
        "/api/v1/operations/": {
            "get": _operation("operations_list", response="PaginatedOperationList")
        },
        "/api/v1/operations/previews/": {
            "post": _operation(
                "action_previews_create",
                response="ActionPreview",
                request="ActionPreviewRequest",
                extra_responses={
                    "403": _response("ApiError", "Recent step-up authentication required")
                },
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
                request="AccessProfileCreate",
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
        "/api/v1/subscriptions/{subscription_id}/tokens/": {
            "get": _operation(
                "subscription_tokens_list",
                response="PaginatedSubscriptionTokenList",
                parameters=uuid("subscription_id"),
            )
        },
        "/api/v1/subscriptions/{subscription_id}/tokens/{token_id}/revoke/": {
            "post": _operation(
                "subscription_token_revoke_create",
                response="SubscriptionTokenRevoke",
                request="SubscriptionTokenRevokeRequest",
                parameters=uuid("subscription_id") + uuid("token_id"),
                extra_responses={
                    "403": _response("ApiError", "Recent step-up authentication required"),
                    "404": _response("ApiError", "Subscription token not found"),
                },
            )
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
        "/api/v1/system": {
            "get": _operation("system_retrieve", response="SystemInfo"),
            "patch": _operation(
                "system_partial_update",
                response="SystemInfo",
                request="SystemSettingsPatch",
            ),
        },
    }
    paths["/api/v1/node-pools/"]["post"]["responses"]["200"] = _response("NodePool")
    policy_properties = {
        "plan_id": {"type": "string", "format": "uuid", "nullable": True},
        "expires_at": {"type": "string", "format": "date-time", "nullable": True},
        "traffic_limit_bytes": {"type": "integer", "nullable": True},
        "upload_bytes": {"type": "integer"},
        "download_bytes": {"type": "integer"},
        "usage_updated_at": {"type": "string", "format": "date-time", "nullable": True},
        "entitlement_state": {"type": "string"},
        "metering_coverage": {"type": "string"},
        "access_sync_pending": {"type": "boolean"},
    }
    schemas["AccessProfile"]["properties"].update(policy_properties)
    schemas["AccessProfileCreate"] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name"],
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120}},
    }
    schemas["AccessProfilePatch"] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120}},
    }
    schemas["Subscription"]["properties"]["policy"] = _ref("AccessProfile")
    schemas["SubscriptionPlan"] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "duration_days": {"type": "integer", "nullable": True},
            "traffic_limit_bytes": {"type": "integer", "nullable": True},
            "enabled": {"type": "boolean"},
        },
    }
    schemas["PaginatedSubscriptionPlanList"] = _page_schema("SubscriptionPlan")
    paths.update(
        {
            "/api/v1/access-profiles/{profile_id}/": {
                "get": _operation(
                    "access_profiles_retrieve",
                    response="AccessProfile",
                    parameters=uuid("profile_id"),
                ),
                "patch": _operation(
                    "access_profiles_update",
                    response="AccessProfile",
                    request="AccessProfilePatch",
                    parameters=uuid("profile_id"),
                ),
            },
            "/api/v1/subscriptions/plans/": {
                "get": _operation(
                    "subscription_plans_list", response="PaginatedSubscriptionPlanList"
                ),
                "post": _operation(
                    "subscription_plans_create",
                    response="SubscriptionPlan",
                    request="GenericObject",
                    status="201",
                ),
            },
            "/api/v1/subscriptions/plans/{plan_id}/": {
                "patch": _operation(
                    "subscription_plans_update",
                    response="SubscriptionPlan",
                    request="GenericObject",
                    parameters=uuid("plan_id"),
                )
            },
            "/api/v1/subscriptions/catalog/": {
                "get": _operation("subscription_protocols_list", response="GenericObject"),
                "post": _operation(
                    "subscription_protocols_create",
                    response="GenericObject",
                    request="GenericObject",
                    status="201",
                ),
            },
            "/api/v1/subscriptions/{subscription_id}/": {
                "get": _operation(
                    "subscriptions_retrieve",
                    response="GenericObject",
                    parameters=uuid("subscription_id"),
                )
            },
            "/api/v1/subscriptions/{subscription_id}/assign/": {
                "post": _operation(
                    "subscriptions_assign",
                    response="GenericObject",
                    request="GenericObject",
                    parameters=uuid("subscription_id"),
                    status="202",
                )
            },
            "/api/v1/subscriptions/{subscription_id}/publish/": {
                "post": _operation(
                    "subscriptions_publish",
                    response="Subscription",
                    parameters=uuid("subscription_id"),
                )
            },
        }
    )
    idempotency = {
        "name": "Idempotency-Key",
        "in": "header",
        "required": True,
        "schema": {"type": "string", "format": "uuid"},
    }
    for path, methods in paths.items():
        if (
            "/subscriptions/" in path
            or "/access-profiles/" in path
            or path == "/api/v1/nodes/"
            or "/api/v1/nodes/{node_id}/refresh/" in path
            or "/api/v1/nodes/{node_id}/actions/" in path
        ):
            for method, operation in methods.items():
                if method in {"post", "patch"}:
                    operation.setdefault("parameters", []).append(idempotency)
    result.setdefault("paths", {}).update(paths)
    return result
