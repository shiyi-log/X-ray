# P2 Cloud Accounts and Dual-cloud Adapters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可独立验证的云账号密文存储、AWS Lightsail / 阿里云 SWAS 适配器和有证据的能力矩阵，为 P3 节点任务提供明确边界。

**Architecture:** 账号服务负责厂商身份与凭据生命周期，适配器只转换云 DTO、请求及结果。只读适配器不能调用写入；每次云写调用前由 P3 提供的 authorizer 重新检查 Operation 授权、数据库租约和 fence。P2 使用拒绝写入的默认实现与假授权器完成 SDK 契约测试。

**Tech Stack:** Python 3.13、Django 5.2 LTS、DRF 3.16、PostgreSQL 17、boto3/botocore、Alibaba Cloud SWAS 2020-06-01 与 STS 2015-04-01 SDK；版本解析后写入 backend/uv.lock。

**Spec:** `docs/superpowers/specs/2026-09-16-xray-manager-design.md`，重点为第 4、5、6、7、10、12 节；前置 P1 完成。

## Global Constraints

- AWS Lightsail 和阿里云 SWAS 同时进入第一版；不实现 ECS。
- Shop、vue-shop-admin、shop-xray-installer 全部只读参考：不改、不删除、不复制历史迁移或运行数据，不导入其模块，不调用其部署资产。
- 本机 `archive/` 是此前完整备份，禁止进入 Git、镜像、安装包、测试发现、文件监控、CI 上传及发布包。新数据库和凭据从零建立。
- 第一版云资源变更由管理员显式发起。一次确认可以授权同一 Operation 的安装、重试、恢复和撤销失败隔离；周期性只读同步不允许隐式建机、换 IP 或删除。
- 能力需要区分 `SUPPORTED / UNSUPPORTED / UNVERIFIED`，并说明区域/套餐限制及证据日期。
- 所有命令从 `/Users/a399/Desktop/data/X-ray` 执行；测试使用 P1 独立 PostgreSQL 环境。每个 checkbox 是约 2–5 分钟的一次编辑、测试或核对；重复方法逐个执行同样测试循环。
- 此计划只使用显式假凭据与 SDK Stub；真实账号、云创建、费用、删除、IP 释放分别进入 P6 授权门禁。

---

## 共享类型与跨阶段契约

以下类型全部在 `backend/providers/base.py` 定义；DTO 使用 `@dataclass(frozen=True, slots=True)`，可选字段明确为 `None`，时间使用 UTC aware datetime，金额使用 Decimal，不包含密文或凭据。`SecretInput` 是唯一含输入秘密的类型，使用 `repr=False`，不进入日志或 Operation 参数。

```python
ProviderKind = Literal["aws_lightsail", "aliyun_swas"]
Action = Literal["create", "start", "stop", "reboot", "delete", "rotate_ip", "firewall", "release_ip", "reinstall"]
# 以下为 dataclass 字段定义；tuple 固定快照，Mapping 不允许返回厂商 SDK 对象。
SecretInput: provider: ProviderKind; fields: Mapping[str, str]  # AWS access_key_id/secret_access_key/session_token?；阿里云 access_key_id/access_key_secret/security_token?
AccountIdentity: provider: ProviderKind; external_account_id: str; principal_id: str; verified_at: datetime
AccountRef: id: UUID; provider: ProviderKind; external_account_id: str; credential_version: int
Region: id: str; name: str
Plan: id: str; region: str; price: Decimal | None; currency: str | None; period: str | None; captured_at: datetime; exclusions: tuple[str, ...]
Image: id: str; region: str; name: str; architecture: str; os_family: str
Address: value: str; family: Literal[4, 6]; kind: Literal["dynamic", "static", "unknown"]; resource_id: str | None
ResourceRef: account: AccountRef; region: str; resource_id: str
Instance: ref: ResourceRef; name: str; state: str; raw_state: str; addresses: tuple[Address, ...]; tags: Mapping[str, str]; observed_at: datetime
CreateRequest: name: str; region: str; plan_id: str; image_id: str; tags: Mapping[str, str]; term: str | None
FirewallRule: protocol: Literal["tcp", "udp", "icmp", "all"]; port_from: int | None; port_to: int | None; source: str; source_kind: Literal["cidr", "provider_alias"]; family: Literal[4, 6]
FirewallSnapshot: rules: tuple[FirewallRule, ...]; observed_at: datetime; request_id: str | None
Capability: name: str; status: Literal["SUPPORTED", "UNSUPPORTED", "UNVERIFIED"]; regions: tuple[str, ...]; plans: tuple[str, ...]; evidence_url: str; checked_at: date; document_verified: bool; stub_verified: bool; live_verified: bool; reason: str
MutationPermit: operation_id: UUID; operation_key: str; action: Action; account_id: UUID; external_account_id: str; region: str; resource_id: str | None; expires_at: datetime; fence: int
MutationResult: outcome: Literal["accepted", "completed", "unknown"]; request_id: str | None; resource_id: str | None; raw_state: str | None; provider_code: str | None
class WriteAuthorizer(Protocol):
    def assert_allowed(self, permit: MutationPermit, *, action: Action, account: AccountRef, resource_id: str | None) -> None: ...
class CloudReader(Protocol):
    def validate_credentials(self) -> AccountIdentity: ...
    def list_regions(self) -> tuple[Region, ...]: ...
    def list_plans(self, region: str) -> tuple[Plan, ...]: ...
    def list_images(self, region: str) -> tuple[Image, ...]: ...
    def find_instance_by_request(self, request: CreateRequest, operation_key: str) -> tuple[Instance, ...]: ...
    def get_instance(self, resource: ResourceRef) -> Instance: ...
    def get_public_ip(self, resource: ResourceRef) -> tuple[Address, ...]: ...
    def get_firewall(self, resource: ResourceRef) -> FirewallSnapshot: ...
    def get_capabilities(self, region: str) -> tuple[Capability, ...]: ...
class CloudProvider(CloudReader, Protocol):
    def create_instance(self, request: CreateRequest, *, permit: MutationPermit) -> MutationResult: ...
    def start_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def stop_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def reboot_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def delete_instance(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def rotate_public_ip(self, resource: ResourceRef, *, permit: MutationPermit) -> MutationResult: ...
    def configure_firewall(self, resource: ResourceRef, rules: tuple[FirewallRule, ...], *, permit: MutationPermit) -> MutationResult: ...
```

`build_read_provider(account_id: UUID, region: str, *, credential_version: int | None = None) -> CloudReader` 与 `build_write_provider(account_id: UUID, region: str, *, authorizer: WriteAuthorizer, credential_version: int | None = None) -> CloudProvider` 在 `backend/providers/registry.py` 定义。None 仅用于管理读取当前版本；P3 运行或对账的 Operation 必须传已绑定版本。只读返回包装对象，没有写方法；写工厂显式注入 authorizer。`assert_allowed` 抛出 P1 `DomainError(code, message, retryable=False, details=None)`；默认 `DenyWrites` 总是抛 `CLOUD_WRITE_NOT_AUTHORIZED`。permit 是数据载体，不是认证凭证；P3 authorizer 每次 SDK 写前回读 Operation、确认范围、step-up 快照、lease/fence、到期时间、账号、凭据版本、区域与资源绑定。工厂绑定 region，适配器拒绝跨区域 ResourceRef。

### Task 1: 云账号身份、密文与只读管理 API

**Files:**
- Create: `backend/apps/cloud_accounts/{apps.py,models.py,services.py,serializers.py,views.py,urls.py,migrations/0001_initial.py}`（并创建两个包的 `__init__.py`）、`backend/providers/{__init__.py,base.py,registry.py,authorization.py}`。
- Modify: `backend/config/settings/base.py`、`backend/config/urls.py`；Test: `backend/tests/cloud_accounts/{test_identity.py,test_api.py,test_secrets.py}`。

**Interfaces:**
- Consumes: `common.crypto.SecretStore.encrypt(plaintext: bytes, *, purpose: str, aad: bytes) -> dict` / `decrypt(envelope: dict, *, purpose: str, aad: bytes) -> bytes`（认证失败抛 `cryptography.exceptions.InvalidTag`）；P1 `DomainError`、正式 MFA 会话/近期认证检查与 P1.3 `authenticated_client` fixture。
- Produces: `create_account(*, name: str, credentials: SecretInput, region: str) -> CloudAccount`、`rotate_credentials(account_id: UUID, *, credentials: SecretInput, region: str) -> CloudAccount`、`validate_account(account_id: UUID, *, region: str) -> AccountIdentity`、`set_account_enabled(account_id: UUID, *, enabled: bool) -> CloudAccount`，均在 services.py。
- `CloudAccount` 字段：id UUID、name、provider、external_account_id、credential_version 当前正整数、enabled、validated_at、last_validation_code；数据库唯一 `(provider, external_account_id)`，provider CHECK 限制两种。`CloudCredentialVersion` 字段：id UUID、account FK(PROTECT)、version 正整数、encrypted_credentials JSON、identity_verified_at、created_at，唯一 `(account, version)`；该业务凭据版本不可原地覆盖，密文仅存在版本表。API serializer 永不输出 encrypted_credentials、SecretInput、principal credential。
- P3 `Operation.cloud_credential_version` FK(PROTECT) 绑定受理时的 immutable 版本；运行/重试/对账始终显式使用同一版本。旧版本至少保留至所有引用 Operation 与不确定结果对账结束，P2 不提供旧版本删除 API；CloudAccount 不提供 DELETE，有资源或未完成 Operation 时必须拒绝硬删，由 P3 资源/任务 FK(PROTECT) 固化保护。
- 端点：`GET/POST /api/v1/cloud-accounts/`、`GET/PATCH /api/v1/cloud-accounts/{uuid}/`、`POST .../{uuid}/validate/`、`POST .../{uuid}/rotate-credentials/`、`GET .../{uuid}/capabilities/?region=...`；PATCH 只接收 name/enabled；创建/轮换输入 credentials，轮换需 P1 step-up。失败保留原密文/版本。

- [ ] **Step 1: 编写账号轮换失败测试，明确“验证身份不同则原凭据保持可用”。**

```python
@pytest.mark.django_db
def test_rotation_cannot_change_cloud_identity(monkeypatch):
    account = CloudAccount.objects.create(name="test", provider="aws_lightsail", external_account_id="111111111111", credential_version=1)
    original = CloudCredentialVersion.objects.create(account=account, version=1, encrypted_credentials={"test": "original"}, identity_verified_at=timezone.now())
    reader = Mock()
    reader.validate_credentials.return_value = AccountIdentity("aws_lightsail", "222222222222", "test-principal", timezone.now())
    monkeypatch.setattr("apps.cloud_accounts.services.reader_for_input", lambda credentials, region: reader)
    with pytest.raises(DomainError) as caught:
        rotate_credentials(account.id, credentials=SecretInput("aws_lightsail", {"access_key_id": "TEST", "secret_access_key": "TEST"}), region="ap-northeast-1")
    assert caught.value.code == "CLOUD_IDENTITY_MISMATCH"
    account.refresh_from_db()
    original.refresh_from_db()
    assert (account.credential_version, original.encrypted_credentials, account.credential_versions.count()) == (1, {"test": "original"}, 1)
```

- [ ] **Step 2: 运行失败测试。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/cloud_accounts/test_identity.py -q`；预期缺失 services/model 导入失败。测试文件显式导入 pytest、Mock、timezone 和上文所定义类型/函数。
- [ ] **Step 3a: 按共享契约建立 DTO、Protocol 与 DenyWrites。** import dataclass/datetime/date/Decimal/UUID/Mapping/Literal/Protocol；dataclass 字段定义转换为各自 class，不把类型清单直接复制成 Python 语句。
- [ ] **Step 3b: 写入账号及凭据版本模型约束并生成独立迁移。** `uv run --project backend python backend/manage.py makemigrations cloud_accounts`；id 默认 uuid4，credential_version 默认 1；版本 FK 的 related_name=`credential_versions`；encrypted_credentials 不允许 API 直写，版本行禁止普通 UPDATE/DELETE。
- [ ] **Step 3c: 实现输入验证 reader 工厂。** 内部 `reader_for_input(credentials: SecretInput, region: str) -> CloudReader` 只构造验证用 reader；测试 monkeypatch 此函数；禁止从默认环境或实例元数据补齐密钥。
- [ ] **Step 3d: 实现创建账号。** 按以下 create 算法生成 UUID、绑定 AAD 并加密；唯一身份冲突转换为 409 `CLOUD_ACCOUNT_EXISTS`。
- [ ] **Step 3e: 实现轮换账号。** 按以下 rotate 算法检查凭据版本及厂商身份；并发版本冲突返回 409 `CLOUD_CREDENTIAL_VERSION_CONFLICT`。
- [ ] **Step 3f: 实现验证与启停。** 使用以下 validate/disable 规则，不把云端观测错误伪装成身份变化。

```text
create/rotate: 先用输入凭据调用官方 STS 身份接口；外部网络不占用数据库长事务。
create: 分配 UUID；检查唯一身份；AAD = UTF8("cloud-account:{uuid}:credentials:1")；
        SecretStore.encrypt(canonical_json(credentials.fields), purpose="control.cloud_credentials", aad=AAD)；同事务插入账号与版本1。
rotate: 在网络前记录当前 credential_version；网络后 select_for_update；版本已变化则 409；
        provider/external_account_id 不同则 CLOUD_IDENTITY_MISMATCH；新版本加 1 后重新加密；
        先插入已验证的新 CloudCredentialVersion，再 promote 账号当前版本；同事务保存验证状态及审计；
        旧版本不变，任何错误事务回滚。Operation 只记录版本外键，不保存原始输入；不从云端吊销旧密钥。
validate: 解密当前版本验证身份；验证失败更新错误摘要，保留身份、密文及最后成功观测时间。
disable: 仅拒绝受理新的写 Operation；已有授权 Operation 用绑定版本继续检查点/恢复/对账；只读验证仍可运行。
```

- [ ] **Step 4a: 实现 serializer 与 CRUD 端点。** 输出白名单 id/name/provider/external_account_id/credential_version/enabled/validated_at/last_validation_code；密码字段 write_only；PATCH 非 name/enabled 字段拒绝 400，不能经 PATCH 绕过凭据轮换。
- [ ] **Step 4b: 实现 validate、rotate-credentials、capabilities 动作端点。** validate 只调用 validate_account，rotate 先经过 P1 近期认证，capabilities 只读静态证据，无云写。
- [ ] **Step 4c: 添加 API 回归断言。** 使用 `authenticated_client`，覆盖未登录/MFA 未完成拒绝、CSRF 缺失拒绝、轮换 step-up、重复真实账号 409、并发轮换 409、DELETE 返回 405；响应断言 `"encrypted_credentials" not in response.json()`。停用拒绝新 Operation 而不撤销既有授权的集成断言由 P3 接入时执行。
- [ ] **Step 4d: 添加密文归属测试。** 创建两条账号，取出各自 CloudCredentialVersion.encrypted_credentials 并在测试内存交换，以对方 UUID/版本构造 AAD 调用 SecretStore.decrypt，两次均 `with pytest.raises(InvalidTag)`；不通过 UPDATE 改动 immutable 版本表。
- [ ] **Step 4e: 添加成功轮换的版本保留测试。** 固定初始 account.credential_version=1，Mock reader 返回相同 external_account_id，rotate 后断言当前版本=2、`account.credential_versions.count() == 2`、版本1密文未变；`build_read_provider(account.id, region, credential_version=1)` 仍使用旧假凭据，省略版本才使用新假凭据，所有 SDK 请求由 Mock 拦截。
- [ ] **Step 5: 运行账号门禁并记录评审检查点。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/cloud_accounts -q`；`uv run --project backend python backend/manage.py makemigrations --check --dry-run`。预期全通过，无真实网络；记录通过的是本地 PostgreSQL/加密/API，云身份真实性仍待 P6。

### Task 2: AWS Lightsail 的可注入适配器与写授权边界

**Files:**
- Create: `backend/providers/aws_lightsail.py`、`backend/providers/errors.py`、`backend/tests/providers/test_aws_lightsail.py`、`backend/tests/providers/test_write_authorization.py`；Modify: `backend/providers/registry.py`、`backend/pyproject.toml`、`backend/uv.lock`。

**Interfaces:**
- Consumes: 共享全部 DTO、`WriteAuthorizer`、`DomainError`；`AwsLightsailProvider(account: AccountRef, region: str, *, lightsail_client: object, sts_client: object, authorizer: WriteAuthorizer)` 接收显式 SDK client。
- Produces: CloudProvider 全部方法；`map_provider_error(provider: ProviderKind, error: Exception, *, write_started: bool) -> DomainError` 仅保留 allowlist 的 provider_code/request_id，输出 `CLOUD_PERMISSION_DENIED`、`CLOUD_THROTTLED`、`CLOUD_INVALID_ARGUMENT`、`CLOUD_WRITE_OUTCOME_UNKNOWN`，不返回 SDK 原始异常正文。

- [ ] **Step 1: 加入拒绝写入的失败测试并运行。** 测试不创建可收费资源，不使用环境 AWS profile。

```python
def test_denied_write_never_reaches_aws():
    account = AccountRef(uuid4(), "aws_lightsail", "111111111111", 1)
    client = Mock()
    provider = AwsLightsailProvider(account, "ap-northeast-1", lightsail_client=client, sts_client=Mock(), authorizer=DenyWrites())
    resource = ResourceRef(account, "ap-northeast-1", "test-node")
    permit = MutationPermit(uuid4(), "test-key", "stop", account.id, account.external_account_id, resource.region, resource.resource_id, timezone.now() + timedelta(minutes=1), 1)
    with pytest.raises(DomainError) as caught:
        provider.stop_instance(resource, permit=permit)
    assert caught.value.code == "CLOUD_WRITE_NOT_AUTHORIZED"
    client.stop_instance.assert_not_called()
```

`uv run --project backend pytest -c backend/pyproject.toml backend/tests/providers/test_write_authorization.py -q`；预期缺失适配器失败。导入使用 datetime.timedelta、uuid.uuid4、unittest.mock.Mock、django.utils.timezone 和共享类型。
- [ ] **Step 2: 添加依赖并核对 SDK shape / 官方操作名。** `uv add --project backend boto3`；`uv run --project backend python -c 'import botocore.session; s=botocore.session.get_session().get_service_model("lightsail"); print(sorted(s.operation_names))'`。对照 [Lightsail API Reference](https://docs.aws.amazon.com/lightsail/2016-11-28/api-reference/Welcome.html)，只读取包元数据，不创建真实 client 发送请求。
- [ ] **Step 3a: 实现身份与区域映射。** STS `get_caller_identity` 返回 Account/Arn/UserId；区域 `get_regions`；用 Stubber 成功/拒绝响应验证 AccountIdentity/Region。所有 client 显式假凭据，Stubber 包住每次测试调用。
- [ ] **Step 3b: 实现套餐与镜像映射。** `get_bundles/get_blueprints` 分页转换 Plan/Image；报价缺字段用 None 并列出 exclusions，测试至少两页及 null 报价。
- [ ] **Step 3c: 实现实例观测与查找。** `get_instance/get_instances` 转 Instance；观测失败抛错误而不是伪造 STOPPED；查找返回所有精确匹配项，两个匹配不得任取一个。
- [ ] **Step 3d: 实现公网地址与端口读取。** `get_instance/get_instance_port_states` 转 Address/FirewallSnapshot；保留 cidrListAliases，不能把宽泛别名漏掉。
- [ ] **Step 4: 逐个实现写方法与不确定结果处理。** 核心顺序如下；`get_instance` 同时核实绑定账号、区域及 `xray-manager`/operation 所有权标签。create 用 CreateRequest 的确定名称及标签，重试前由 P3 调用 find_instance_by_request；AWS 不支持相应请求 token 时不得编造 token 参数。

```python
def stop_instance(self, resource, *, permit):
    self.authorizer.assert_allowed(permit, action="stop", account=self.account, resource_id=resource.resource_id)
    self.get_instance(resource)  # 不匹配项目归属时抛 RESOURCE_OWNERSHIP_MISMATCH
    self.authorizer.assert_allowed(permit, action="stop", account=self.account, resource_id=resource.resource_id)
    response = self.lightsail.stop_instance(instanceName=resource.resource_id)
    return MutationResult("accepted", response["ResponseMetadata"]["RequestId"], resource.resource_id, None, None)
```

- [ ] **Step 4a: 按 stop 模板实现 start/reboot。** 调用 `start_instance/reboot_instance`，替换对应 action；Stubber 验证 requestId 和 accepted，不把受理当执行完毕。
- [ ] **Step 4b: 实现 delete 和 create。** 分别 `delete_instance/create_instances`；create 的 action=create、resource_id=None；删除前读取归属。Stubber 断言误绑定资源时没有 SDK 写。
- [ ] **Step 4c: 实现错误分类与单次 SDK 写尝试。** 异步响应仅 accepted；read-after-write 才能确认 completed。SDK 写请求发出后超时抛 CLOUD_WRITE_OUTCOME_UNKNOWN、retryable=False，P3 转 NEEDS_RECONCILIATION；botocore Config 设置 retries={"total_max_attempts": 1}，避免 SDK 暗中重放。
- [ ] **Step 5: 实现防火墙完整规则集更新与 IP 能力保护。** `configure_firewall` 回读全部现存规则，核对项目归属，保留管理员来源 SSH，清理宽泛 allow、IPv6 与 UDP 漏洞后使用 `put_instance_public_ports`，再回读。返回 completed 仅表示规则一致，P3 外部探测决定 IsolationResult.confirmed。静态 IP 的 allocate/attach/detach/release 是不同副作用；P2 `rotate_public_ip` 若缺逐步 checkpoint 与完整支持证据则抛 `CAPABILITY_UNVERIFIED`，不偷偷释放旧 IP；P3 补齐才提升能力。
- [ ] **Step 6: 运行 AWS 与授权回归门禁。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/providers/test_aws_lightsail.py backend/tests/providers/test_write_authorization.py -q`。覆盖重复创建查询、分页、跨账号/区域、过期 permit、过期 fence、伪造 permit、归属不明、已有宽泛端口规则、写超时不自动重试；断言每个 SDK 写均先调用 authorizer，零真实云调用。

### Task 3: 阿里云 SWAS、能力证据与跨云契约

**Files:**
- Create: `backend/providers/aliyun_swas.py`、`backend/providers/capabilities.py`、`backend/tests/providers/test_aliyun_swas.py`、`backend/tests/providers/test_contract.py`、`docs/architecture/cloud-capabilities.md`。
- Modify: `backend/providers/registry.py`、`backend/pyproject.toml`、`backend/uv.lock`。

**Interfaces:**
- Consumes: CloudProvider、AccountRef、WriteAuthorizer、map_provider_error；`AliyunSwasProvider(account: AccountRef, region: str, *, swas_client: object, sts_client: object, authorizer: WriteAuthorizer)`。
- Produces: 全部 CloudProvider 方法；`capabilities_for(provider: ProviderKind, region: str) -> tuple[Capability, ...]` 供两个适配器调用；P3 对 UNSUPPORTED/UNVERIFIED 直接拒绝按钮对应动作，不把未知能力自动转成收费替代流程。

- [ ] **Step 1: 写阿里云不支持原地换 IP 的失败测试。** 同时固定“没有调用未知 API / 没有新建替代实例”。

```python
def test_swas_rotate_ip_is_explicitly_blocked():
    account = AccountRef(uuid4(), "aliyun_swas", "test-account", 1)
    client = Mock()
    provider = AliyunSwasProvider(account, "ap-southeast-1", swas_client=client, sts_client=Mock(), authorizer=DenyWrites())
    resource = ResourceRef(account, "ap-southeast-1", "test-instance")
    with pytest.raises(DomainError) as caught:
        provider.rotate_public_ip(resource, permit=None)
    assert caught.value.code in {"CAPABILITY_UNSUPPORTED", "CAPABILITY_UNVERIFIED"}
    assert client.mock_calls == []
```

测试用 `None` 是运行时恶意输入，生产类型仍要求 MutationPermit；能力已关闭时先拒绝该动作。`uv run --project backend pytest -c backend/pyproject.toml backend/tests/providers/test_aliyun_swas.py -q`，预期缺失适配器失败。
- [ ] **Step 2: 锁定 SDK 并读取生成的方法清单。** `uv add --project backend alibabacloud-swas-open20200601 alibabacloud-sts20150401`；`uv run --project backend python -c 'from alibabacloud_swas_open20200601.client import Client; print(sorted(n for n in dir(Client) if not n.startswith("_")))'`。逐项对照 [SWAS 2020-06-01 API](https://api.aliyun.com/product/SWAS-OPEN) 与 [STS GetCallerIdentity](https://api.aliyun.com/api/Sts/2015-04-01/GetCallerIdentity)，记录查询日期和区域限制。
- [ ] **Step 3a: 实现身份、区域与套餐读取。** STS AccountId/PrincipalId 提取真实账号身份；SWAS ListRegions/ListPlans 转换 Region/Plan；用 SDK 模型构造正常、分页及拒绝响应 fixture，真实请求入口由 Mock 拦截。
- [ ] **Step 3b: 实现镜像与实例读取。** ListImages/ListInstances 转 Image/Instance；查找同时匹配名称/标签、区域、账号及 operation 标识，多匹配返回集合供 P3 对账。若 SDK 缺标签查询，使用确定名称+持久化 request_id 的证据链，不能唯一确认时禁止重建。
- [ ] **Step 3c: 实现地址与防火墙读取。** ListInstances/ListFirewallRules 转 Address/FirewallSnapshot；逐页读取所有规则，未知 IPv6 支持不能解释为没有 IPv6 入口。
- [ ] **Step 4a: 实现 CreateInstances。** 按生成请求模型传参，先验证 authorizer；核实 ClientToken，支持时使用 operation_key，按 SDK schema 校验长度；若没有 token，则依赖 P3 确定命名与对账，不伪造幂等参数。
- [ ] **Step 4b: 实现 StartInstance/StopInstance/RebootInstance。** 每个方法前后各运行一次相应 Mock 请求/响应测试；写前重新验证 authorizer；仅受理返回 accepted。
- [ ] **Step 4c: 实现 DeleteInstances 与失败映射。** 验证归属、资源 ID 与独立删除授权；记录 request_id；写超时走 CLOUD_WRITE_OUTCOME_UNKNOWN。SDK RuntimeOptions.autoretry=False，默认凭据链关闭。
- [ ] **Step 4d: 实现 CreateFirewallRule/DeleteFirewallRule 协调。** 按下方算法逐条更新，每个 SDK 写之前再次验证 permit；规则回读失败保留不确定结果，不误报隔离成功。

```text
configure_firewall: 读全量规则与项目归属 -> 计算 desired(管理SSH + 指定协议规则)；
                   先逐条删除宽泛/旧协议放行(每次重验permit) -> 添加缺失的窄规则；
                   回读比较IPv4/IPv6及TCP/UDP；无法覆盖IPv6时能力为UNVERIFIED，禁止报告隔离完成。
rotate_public_ip: 读取静态能力 -> UNSUPPORTED/UNVERIFIED 抛同名 DomainError；绝不创建替代实例。
delete_instance: 复核归属与删除授权 -> 调用已验证删除API -> accepted；续读确认消失后才 completed。
```

- [ ] **Step 5: 写可审计能力矩阵和共同契约测试。** 文档逐行覆盖身份验证、区域/套餐/镜像、建机、查找、启停/重启、删除、静态 IP、原地换 IP、重装、退款/停止计费、IPv4/IPv6/TCP/UDP 防火墙；每行保留文档 URL、核对日期、套餐/区域限制以及 document/stub/live 三个独立布尔值。SUPPORTED 要求实现+文档+Stub 全部成立；真实云未测一律 live_verified=False。无报价来源用 None，不显示零成本；停机不等于停止计费。
- [ ] **Step 6: 运行完整 P2 门禁。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests/cloud_accounts backend/tests/providers -q`；`uv run --project backend python backend/manage.py check`；`uv run --project backend python backend/manage.py makemigrations --check --dry-run`。共同契约参数化两个 provider，覆盖 DTO/原始状态、禁止默认密钥链、失败脱敏、分页、禁用账号、写授权、未知结果以及 capability 不能越级。

## P2 完成与 P3 交接

- [ ] 本地门禁输出写入 `docs/architecture/cloud-capabilities.md` 的验收记录；保留准确日期、锁定 SDK 版本、测试命令/退出码，真实云列保持未执行。
- [ ] P3 通过 registry 与共享 DTO 对接；在接入数据库授权器前所有运行时云写默认拒绝。防火墙规则已应用与数据面已经隔离是两个结果，P3 输出 `IsolationResult(confirmed, evidence)`。
- [ ] P3 为 AWS 静态 IP 多步骤写建立 OperationStep/checkpoint 与单独释放确认后，再补 Stub/文档证据提升能力；阿里云原地 IP 不支持时采用显式确认、计入配额的替代节点流程。
- [ ] 检查本阶段 diff 仅为上述新项目文件；凭据、测试数据库、archive、Shop 资产不得进入 diff。提交由主计划执行时统一安排，本计划编写阶段不提交、不创建云资源。
