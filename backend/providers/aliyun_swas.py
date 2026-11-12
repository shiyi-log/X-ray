from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from common.errors import DomainError

from .authorization import DenyWrites
from .base import (
    AccountIdentity,
    AccountRef,
    Address,
    Capability,
    CreateRequest,
    FirewallRule,
    FirewallSnapshot,
    Image,
    Instance,
    MutationPermit,
    MutationResult,
    Plan,
    Region,
    ResourceRef,
)
from .capabilities import capabilities_for
from .errors import map_provider_error


class AliyunSwasProvider:
    provider = "aliyun_swas"

    def __init__(
        self,
        account: AccountRef,
        region: str,
        *,
        swas_client: object,
        sts_client: object,
        authorizer=None,
    ):
        self.account = account
        self.region = region
        self.swas = swas_client
        self.sts = sts_client
        self.authorizer = authorizer or DenyWrites()

    @classmethod
    def from_credentials(cls, account, region: str, fields: dict[str, str], *, authorizer):
        if not fields.get("access_key_id") or not fields.get("access_key_secret"):
            raise DomainError("CLOUD_CREDENTIALS_INVALID", "阿里云凭据字段不完整", status_code=400)
        from alibabacloud_sts20150401.client import Client as StsClient
        from alibabacloud_swas_open20200601.client import Client
        from alibabacloud_tea_openapi.models import Config

        common = {
            "access_key_id": fields["access_key_id"],
            "access_key_secret": fields["access_key_secret"],
            "security_token": fields.get("security_token"),
            "endpoint": fields.get("endpoint"),
        }
        swas_config = Config(**{key: value for key, value in common.items() if value})
        sts_config = Config(**{key: value for key, value in common.items() if value})
        return cls(
            account,
            region,
            swas_client=Client(swas_config),
            sts_client=StsClient(sts_config),
            authorizer=authorizer,
        )

    def _assert_region(self, resource: ResourceRef):
        if resource.account != self.account or resource.region != self.region:
            raise DomainError(
                "RESOURCE_OWNERSHIP_MISMATCH", "资源不属于当前云账号或区域", status_code=409
            )

    @staticmethod
    def _request_id(response: Any) -> str | None:
        for key in ("request_id", "RequestId", "RequestID"):
            value = (
                response.get(key) if isinstance(response, dict) else getattr(response, key, None)
            )
            if value:
                return str(value)[:120]
        return None

    @staticmethod
    def _body(response: Any) -> Any:
        if isinstance(response, dict):
            body = response.get("body", response)
        else:
            body = getattr(response, "body", response)
        to_map = getattr(body, "to_map", None)
        return to_map() if callable(to_map) else body

    def validate_credentials(self) -> AccountIdentity:
        try:
            result = self.sts.get_caller_identity()
            body = self._body(result)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        account_id = str(
            (body.get("AccountId") if isinstance(body, dict) else None)
            or (body.get("account_id") if isinstance(body, dict) else None)
            or ""
        )
        principal = str(
            (body.get("PrincipalId") if isinstance(body, dict) else None)
            or (body.get("principal_id") if isinstance(body, dict) else None)
            or ""
        )
        if not account_id or not principal:
            raise DomainError(
                "CLOUD_IDENTITY_INVALID", "阿里云身份响应缺少必要字段", status_code=502
            )
        return AccountIdentity(self.provider, account_id, principal, datetime.now(UTC))

    def _read(self, name: str, **kwargs):
        method = getattr(self.swas, name, None)
        if method is None:
            raise DomainError(
                "CLOUD_CAPABILITY_UNVERIFIED", f"SWAS SDK 未提供 {name}", status_code=409
            )
        try:
            return self._body(method(**kwargs))
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc

    def list_regions(self) -> tuple[Region, ...]:
        try:
            from alibabacloud_swas_open20200601.models import ListRegionsRequest

            body = self._body(self.swas.list_regions(ListRegionsRequest()))
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=False) from exc
        if not isinstance(body, dict) or not any(key in body for key in ("regions", "Regions")):
            raise DomainError(
                "CLOUD_INVENTORY_RESPONSE_INVALID",
                "SWAS 区域清单响应格式无效",
                status_code=502,
            )
        values = body.get("regions", body.get("Regions", []))
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise DomainError(
                "CLOUD_INVENTORY_RESPONSE_INVALID",
                "SWAS 区域清单响应格式无效",
                status_code=502,
            )
        if any(not (item.get("region_id") or item.get("RegionId")) for item in values):
            raise DomainError(
                "CLOUD_INVENTORY_RESPONSE_INVALID",
                "SWAS 区域清单缺少区域标识",
                status_code=502,
            )
        region_ids = [item.get("region_id") or item.get("RegionId") for item in values]
        if len(set(region_ids)) != len(region_ids):
            raise DomainError(
                "CLOUD_INVENTORY_RESPONSE_INVALID",
                "SWAS 区域清单包含重复区域标识",
                status_code=502,
            )
        return tuple(
            Region(
                str(item.get("region_id") or item.get("RegionId")),
                str(
                    item.get("local_name")
                    or item.get("LocalName")
                    or item.get("name")
                    or item.get("RegionName")
                    or item.get("RegionId")
                ),
            )
            for item in values
        )

    def list_plans(self, region: str) -> tuple[Plan, ...]:
        if region != self.region:
            raise DomainError("REGION_MISMATCH", "适配器已绑定其他区域", status_code=400)
        body = self._read("list_plans", region_id=region)
        values = body.get("plans", body.get("Plans", [])) if isinstance(body, dict) else []
        return tuple(
            Plan(
                str(item.get("plan_id") or item.get("PlanId")),
                region,
                None,
                None,
                None,
                datetime.now(UTC),
                ("price unavailable",),
            )
            for item in values
        )

    def list_images(self, region: str) -> tuple[Image, ...]:
        if region != self.region:
            raise DomainError("REGION_MISMATCH", "适配器已绑定其他区域", status_code=400)
        body = self._read("list_images", region_id=region)
        values = body.get("images", body.get("Images", [])) if isinstance(body, dict) else []
        return tuple(
            Image(
                str(item.get("image_id") or item.get("ImageId")),
                region,
                str(item.get("name") or item.get("ImageName") or ""),
                str(item.get("architecture") or "unknown"),
                str(item.get("os_family") or "unknown"),
            )
            for item in values
        )

    def _map_instance(self, item: dict[str, Any]) -> Instance:
        resource_id = str(item.get("instance_id") or item.get("InstanceId") or "")
        addresses = []
        address = (
            item.get("public_ip")
            or item.get("public_ip_address")
            or item.get("PublicIpAddress")
        )
        if address:
            addresses.append(Address(str(address), 4, "dynamic", resource_id))
        ref = ResourceRef(self.account, self.region, resource_id)
        raw_tags = item.get("tags", item.get("Tags", []))
        if isinstance(raw_tags, dict):
            tags = {str(key): str(value) for key, value in raw_tags.items()}
        elif isinstance(raw_tags, list) and all(isinstance(tag, dict) for tag in raw_tags):
            tags = {
                str(tag.get("key") or tag.get("Key")): str(
                    tag.get("value") or tag.get("Value") or ""
                )
                for tag in raw_tags
                if tag.get("key") or tag.get("Key")
            }
        else:
            raise ValueError("invalid SWAS instance tags")
        return Instance(
            ref,
            str(
                item.get("name")
                or item.get("instance_name")
                or item.get("InstanceName")
                or resource_id
            ),
            str(item.get("state") or item.get("status") or item.get("Status") or "UNKNOWN"),
            str(item.get("Status") or item.get("status") or item.get("state") or "UNKNOWN"),
            tuple(addresses),
            tags,
            datetime.now(UTC),
        )

    def list_instances(self, region: str) -> tuple[Instance, ...]:
        if region != self.region:
            raise DomainError("REGION_MISMATCH", "适配器已绑定其他区域", status_code=400)
        values = []
        page_number = 1
        seen_ids = set()
        total_count = None
        while True:
            try:
                from alibabacloud_swas_open20200601.models import ListInstancesRequest

                response = self.swas.list_instances(
                    ListInstancesRequest(
                        region_id=region,
                        page_number=page_number,
                        page_size=100,
                    )
                )
                body = self._body(response)
            except Exception as exc:
                raise map_provider_error(self.provider, exc, write_started=False) from exc
            if not isinstance(body, dict):
                raise DomainError(
                    "CLOUD_INVENTORY_RESPONSE_INVALID",
                    "SWAS 实例清单响应格式无效",
                    status_code=502,
                )
            if (
                ("instances" not in body and "Instances" not in body)
                or ("total_count" not in body and "TotalCount" not in body)
            ):
                raise DomainError(
                    "CLOUD_INVENTORY_RESPONSE_INVALID",
                    "SWAS 实例清单响应格式无效",
                    status_code=502,
                )
            page_items = body.get("instances", body.get("Instances", []))
            if not isinstance(page_items, list) or any(
                not isinstance(item, dict) for item in page_items
            ):
                raise DomainError(
                    "CLOUD_INVENTORY_RESPONSE_INVALID",
                    "SWAS 实例清单响应格式无效",
                    status_code=502,
                )
            count = body.get("total_count", body.get("TotalCount"))
            valid_count = isinstance(count, int) and not isinstance(count, bool)
            if isinstance(count, str) and count.isdecimal():
                count = int(count)
                valid_count = True
            if not valid_count:
                raise DomainError(
                    "CLOUD_INVENTORY_PAGINATION_INVALID",
                    "SWAS 实例清单总数无效",
                    status_code=502,
                )
            if count < 0 or (total_count is not None and count != total_count):
                raise DomainError(
                    "CLOUD_INVENTORY_PAGINATION_INVALID",
                    "SWAS 实例清单总数不一致",
                    status_code=502,
                )
            total_count = count
            if not page_items and total_count is not None and len(values) < total_count:
                raise DomainError(
                    "CLOUD_INVENTORY_PAGINATION_INVALID",
                    "SWAS 实例清单分页提前结束",
                    status_code=502,
                )
            if not page_items:
                break
            for item in page_items:
                instance_id = str(item.get("instance_id") or item.get("InstanceId") or "")
                if not instance_id or instance_id in seen_ids:
                    raise DomainError(
                        "CLOUD_INVENTORY_RESPONSE_INVALID",
                        "SWAS 实例清单包含无效或重复实例标识",
                        status_code=502,
                    )
                seen_ids.add(instance_id)
            values.extend(page_items)
            if total_count is not None and len(values) >= total_count:
                if len(values) != total_count:
                    raise DomainError(
                        "CLOUD_INVENTORY_PAGINATION_INVALID",
                        "SWAS 实例清单超过报告总数",
                        status_code=502,
                    )
                break
            if page_number >= 10000:
                raise DomainError(
                    "CLOUD_INVENTORY_PAGINATION_INVALID",
                    "SWAS 实例清单分页超出安全上限",
                    status_code=502,
                )
            page_number += 1
        try:
            return tuple(self._map_instance(item) for item in values)
        except Exception as exc:
            raise DomainError(
                "CLOUD_INVENTORY_RESPONSE_INVALID",
                "SWAS 实例清单响应格式无效",
                status_code=502,
            ) from exc

    def find_instance_by_request(
        self, request: CreateRequest, operation_key: str
    ) -> tuple[Instance, ...]:
        return tuple(
            instance
            for instance in self.list_instances(self.region)
            if instance.name == request.name
            and instance.tags.get("xray-operation") == operation_key
        )

    def get_instance(self, resource: ResourceRef) -> Instance:
        self._assert_region(resource)
        item = self._read("get_instance", instance_id=resource.resource_id)
        if isinstance(item, dict) and "instance" in item:
            item = item["instance"]
        if not item:
            raise DomainError("RESOURCE_NOT_FOUND", "云实例不存在", status_code=404)
        return self._map_instance(item)

    def get_public_ip(self, resource: ResourceRef) -> tuple[Address, ...]:
        return self.get_instance(resource).addresses

    def get_firewall(self, resource: ResourceRef) -> FirewallSnapshot:
        self._assert_region(resource)
        body = self._read("list_firewall_rules", instance_id=resource.resource_id)
        values = body.get("rules", body.get("Rules", [])) if isinstance(body, dict) else []
        rules = []
        for item in values:
            source = str(item.get("source") or item.get("SourceCidrIp") or "")
            rules.append(
                FirewallRule(
                    str(item.get("protocol") or "all").lower(),
                    item.get("from_port"),
                    item.get("to_port"),
                    source,
                    "cidr",
                    6 if ":" in source else 4,
                )
            )
        return FirewallSnapshot(tuple(rules), datetime.now(UTC), self._request_id(body))

    def get_capabilities(self, region: str) -> tuple[Capability, ...]:
        return capabilities_for(self.provider, region)

    def _write(
        self, action: str, resource: ResourceRef, permit: MutationPermit, method_name: str, **kwargs
    ) -> MutationResult:
        self._assert_region(resource)
        self.authorizer.assert_allowed(
            permit, action=action, account=self.account, resource_id=resource.resource_id
        )
        self.get_instance(resource)
        self.authorizer.assert_allowed(
            permit, action=action, account=self.account, resource_id=resource.resource_id
        )
        method = getattr(self.swas, method_name, None)
        if method is None:
            raise DomainError(
                "CLOUD_CAPABILITY_UNVERIFIED", f"SWAS SDK 未提供 {method_name}", status_code=409
            )
        try:
            response = method(instance_id=resource.resource_id, **kwargs)
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult(
            "accepted", self._request_id(response), resource.resource_id, None, None
        )

    def create_instance(self, request: CreateRequest, *, permit: MutationPermit) -> MutationResult:
        self.authorizer.assert_allowed(
            permit, action="create", account=self.account, resource_id=None
        )
        if request.region != self.region:
            raise DomainError("REGION_MISMATCH", "创建区域与适配器不一致", status_code=400)
        method = getattr(self.swas, "create_instance", None)
        if method is None:
            raise DomainError(
                "CLOUD_CAPABILITY_UNVERIFIED", "SWAS 建机 SDK 未核验", status_code=409
            )
        try:
            response = method(
                name=request.name,
                region_id=request.region,
                plan_id=request.plan_id,
                image_id=request.image_id,
                tags=dict(request.tags),
                operation_key=permit.operation_key,
            )
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult("accepted", self._request_id(response), None, None, None)

    def start_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._write("start", resource, permit, "start_instance")

    def stop_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._write("stop", resource, permit, "stop_instance")

    def reboot_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._write("reboot", resource, permit, "reboot_instance")

    def delete_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        return self._write("delete", resource, permit, "delete_instance")

    def rotate_public_ip(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult:
        raise DomainError(
            "CAPABILITY_UNSUPPORTED", "SWAS 原地换 IP 不支持，使用替代节点流程", status_code=409
        )

    def configure_firewall(
        self, resource: ResourceRef, rules: tuple[FirewallRule, ...], *, permit: MutationPermit
    ) -> MutationResult:
        self._assert_region(resource)
        self.authorizer.assert_allowed(
            permit, action="firewall", account=self.account, resource_id=resource.resource_id
        )
        method = getattr(self.swas, "configure_firewall", None)
        if method is None:
            raise DomainError(
                "CLOUD_CAPABILITY_UNVERIFIED", "SWAS 防火墙 SDK 未核验", status_code=409
            )
        try:
            response = method(
                instance_id=resource.resource_id,
                rules=[
                    rule.__dict__
                    if hasattr(rule, "__dict__")
                    else {
                        "protocol": rule.protocol,
                        "from_port": rule.port_from,
                        "to_port": rule.port_to,
                        "source": rule.source,
                    }
                    for rule in rules
                ],
            )
        except Exception as exc:
            raise map_provider_error(self.provider, exc, write_started=True) from exc
        return MutationResult(
            "accepted", self._request_id(response), resource.resource_id, None, None
        )
