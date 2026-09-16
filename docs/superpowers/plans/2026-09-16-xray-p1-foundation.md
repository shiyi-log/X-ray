# P1 仓库基础与唯一超级管理员 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立独立后端和专用测试环境，交付唯一超级管理员、MFA、会话、加密及 API 基础。

**Architecture:** 自定义 Django 用户从初始迁移定义，PostgreSQL 约束保证单例。服务器会话和 purpose 隔离的信封加密为后续云管理与订阅提供基础。

**Tech Stack:** Python 3.13、Django 5.2、DRF 3.16、PostgreSQL 17、Redis 7.4、pytest/pytest-django、cryptography、argon2-cffi、pyotp、drf-spectacular。

**Spec:** [设计规格](../specs/2026-09-16-xray-manager-design.md)，章节 1–5、10。

## Global Constraints

- 新仓库根目录 `/Users/a399/Desktop/data/X-ray`；Shop 只读，archive/ 禁止进入构建和测试。
- 唯一超级管理员，无注册或第二个后台用户；TOTP 与会话服务器侧验证。
- Python 3.13、Django 5.2、PostgreSQL 17；测试使用新建独立 PostgreSQL 库，无 SQLite 替代。
- 仅本地实现与模拟服务，零真实云请求；规格的全部全局约束适用。

---

### Task P1.1: 建立能独立检查的 API 基线

**Files:**
- Create: `backend/pyproject.toml`、`backend/uv.lock`、`backend/manage.py`、`backend/config/settings/{base,test,development,production}.py`、`backend/config/{urls,subscription_urls,wsgi,celery}.py`。
- Create: `backend/common/{errors,api,logging}.py`、`backend/tests/{conftest,test_boundary,test_health}.py`。
- Create: `deploy/compose/test.yml`、`backend/.env.example`、`.dockerignore`、`docs/development.md`、`docs/progress.md`。
- Modify: `.gitignore`、`README.md`；保留已有根目录空骨架。

**Interfaces:**
- Consumes: 规格的技术基线与目录边界。
- Produces: `DomainError(code, message, retryable=False, details=None)`、DRF 异常格式；`/health/live` 与内部 `/health/ready`；`config.settings.test`。
- Test DB 固定 `xray_test`，pytest 数据库 `test_xray_test`，Compose 项目名 `xray-test`；端口仅 127.0.0.1，先检查占用再选本项目端口，写入文档，不抢占其他服务。

- [ ] **Step 1: 写失败测试，验证健康接口与源码边界。**

```python
# backend/tests/test_health.py
def test_liveness_without_business_data(client):
    response = client.get('/health/live')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}

# backend/tests/test_boundary.py
import ast
from pathlib import Path

def test_no_shop_imports():
    banned = {'shop', 'orders', 'core', 'cloud'}
    for path in Path('backend').rglob('*.py'):
        for item in ast.walk(ast.parse(path.read_text())):
            roots = ([alias.name.split('.')[0] for alias in item.names]
                     if isinstance(item, ast.Import) else
                     [(item.module or '').split('.')[0]]
                     if isinstance(item, ast.ImportFrom) else [])
            assert not banned.intersection(roots), str(path)
```

- [ ] **Step 2: 建立 pyproject 测试依赖和 test Compose，启动隔离服务后运行失败测试。**

```bash
docker compose -p xray-test -f deploy/compose/test.yml up -d --wait
uv sync --project backend --group test
uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_health.py -q
```

初次应因缺少健康路由失败，不能是连到 Shop DB 的错误。pyproject 配置 `DJANGO_SETTINGS_MODULE="config.settings.test"`、`pythonpath=["."]`、`django_find_project=false`；test 设置只从 `XRAY_TEST_DATABASE_URL` 读取并断言数据库名/项目隔离。

- [ ] **Step 3: 实现健康、错误、脱敏与 URL 分离。**

```python
class DomainError(Exception):
    def __init__(self, code, message, retryable=False, details=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.retryable, self.details = retryable, details or {}

def liveness(request):
    return JsonResponse({'status': 'ok'})
```

ready 单独检查专用 DB 和 Redis，不暴露连接串。`subscription_urls` 初始为空，不 include 管理 URL。脱敏基于字段 allowlist，原始 exception/SDK payload 不直接串入响应。Docker context 首先排除 `/archive/`，未来发布只 copy 明确应用目录。

- [ ] **Step 4: 运行边界与健康检查，记录空数据库结果。**

```bash
uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_boundary.py backend/tests/test_health.py -q
uv run --project backend python backend/manage.py check --settings=config.settings.test
docker compose -p xray-test -f deploy/compose/test.yml config --quiet
git check-ignore archive/shop-20260916-fe53b700/.env
git diff --check
```

- [ ] **Step 5: 只提交本任务新增配置、文档与测试。** `git add backend deploy/compose/test.yml .dockerignore .gitignore README.md docs/development.md docs/progress.md` 后复查 `git diff --cached --stat`，提交 `chore: establish isolated xray backend foundation`。

### Task P1.2: 单例账号、信封加密和审计

**Files:**
- Create: `backend/apps/identity/{models,managers}.py`、`backend/apps/identity/migrations/0001_initial.py`、`backend/apps/identity/management/commands/bootstrap_superadmin.py`。
- Create: `backend/common/crypto.py`、`backend/apps/audit/{models,services}.py` 及初始迁移。
- Test: `backend/tests/test_identity_model.py`、`backend/tests/test_crypto.py`、`backend/tests/test_audit.py`。
- Modify: `backend/config/settings/base.py`（AUTH_USER_MODEL 必须在第一次迁移前设好）。

**Interfaces:**
- Produces: `SuperAdmin.objects.create_superuser(username,password)`；`AuditService.append(*,action,target_type,target_id,result,metadata)->AuditEvent`。
- Produces: `SecretStore.encrypt(plaintext:bytes,*,purpose:str,aad:bytes)->dict`、`decrypt(envelope:dict,*,purpose:str,aad:bytes)->bytes`；purpose 限定 control/subscription，envelope 包含 key_version/wrapped_dek/nonce/ciphertext。

- [ ] **Step 1: 写失败测试，包括并发创建和密文错绑。**

```python
@pytest.mark.django_db(transaction=True)
def test_database_rejects_second_admin():
    SuperAdmin.objects.create_superuser('owner', 'test-only-password-A')
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SuperAdmin.objects.create_superuser('second', 'test-only-password-B')

def test_ciphertext_cannot_move_between_records(secret_store):
    envelope = secret_store.encrypt(b'fake-key', purpose='control', aad=b'account:1')
    assert secret_store.decrypt(envelope, purpose='control', aad=b'account:1') == b'fake-key'
    with pytest.raises(InvalidTag):
        secret_store.decrypt(envelope, purpose='control', aad=b'account:2')
```

`secret_store` fixture 在 conftest 使用临时生成的两个主密钥，不读生产路径。补 PostgreSQL 两连接并发创建、数据库 CHECK 阻止 singleton_key≠1、审计元数据拒绝秘密字段用例。

- [ ] **Step 2: 运行 `uv run --project backend pytest -c backend/pyproject.toml backend/tests/test_identity_model.py backend/tests/test_crypto.py backend/tests/test_audit.py -q`，确认缺少模型/接口的预期失败。**

- [ ] **Step 3: 建立数据库级唯一管理员约束和加密实现。**

```python
singleton_key = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
# Model.Meta.constraints
models.CheckConstraint(condition=models.Q(singleton_key=1), name='only_admin_slot_one')

# SecretStore.encrypt 的核心，DEK 每条独立，主密钥按 purpose/version 选取
dek = AESGCM.generate_key(bit_length=256)
nonce = secrets.token_bytes(12)
ciphertext = AESGCM(dek).encrypt(nonce, plaintext, aad)
```

包装 DEK 也使用独立 nonce 和绑定 purpose/version/record 的 AAD；禁止 nonce 复用和把 DEK 原文存入 envelope。bootstrap 通过 getpass 交互录入，事务创建；AuditEvent 禁止普通应用更新/删除 API，数据库角色限制覆盖由 P6 完成。

- [ ] **Step 4: 生成初始迁移并运行上述测试与 `makemigrations --check --dry-run`。** 检查迁移包含独立 auth user、唯一/检查约束和 audit 表，不依赖任何 Shop migration。
- [ ] **Step 5: 选择性提交模型、迁移、测试及配置。** 提交名 `feat: add single administrator and encrypted secret storage`。

### Task P1.3: 密码/MFA、会话、CSRF 与本机恢复

**Files:**
- Create: `backend/apps/identity/{authentication,services,serializers,views,urls}.py`、`backend/apps/identity/management/commands/recover_superadmin.py`。
- Create: `backend/apps/identity/migrations/0002_sessions_mfa.py`、`backend/tests/{test_auth_api,test_mfa,test_session_revocation}.py`。
- Modify: `backend/config/{urls.py,settings/base.py,settings/production.py}`、`docs/development.md`。

**Interfaces:**
- Produces: GET `/api/v1/auth/csrf`、POST `login`/`totp/setup`/`totp/confirm`/`totp/verify`/`recovery-code`/`step-up`/`logout`/`logout-all`/`change-password`、GET `session`；URI 相对 `/api/v1/auth/`。
- `AuthService.password_login(request,username,password)->challenge_id`；`complete_mfa(request,challenge_id,code)->AdminSession`；`revoke_all(admin_id)->None`。
- session 响应仅 `authenticated,mfa_required,expires_at,recent_auth_until` 和管理员公开标识，无云或订阅秘密。

- [ ] **Step 1: 写最关键的失败测试。**

```python
@pytest.mark.django_db
def test_password_only_cannot_access_management(client):
    SuperAdmin.objects.create_superuser('owner', 'test-only-password-A')
    client.post('/api/v1/auth/login', {'username': 'owner', 'password': 'test-only-password-A'})
    assert client.get('/api/v1/auth/session').json()['authenticated'] is False
    assert client.get('/api/v1/system').status_code in (401, 403)
```

其他用例覆盖 CSRF 拒绝、首次绑定门禁、同一 TOTP 时间步重放、恢复码两并发仅一次成功、过期/旧 session_version 拒绝、来源 IP 伪造和登录双限速。为 `test_session_revocation.py` 定义 `authenticated_client` fixture：走真实 password/TOTP API，使用测试冻结时间，不跳过认证。

- [ ] **Step 2: 运行三个 auth 测试文件确认失败。** 命令沿用本阶段 pytest 入口，不能以关闭 CSRF 使测试通过。
- [ ] **Step 3: 实现服务器会话和事务消费 MFA。**

```python
with transaction.atomic():
    admin = SuperAdmin.objects.select_for_update().get(singleton_key=1)
    if verified_step <= admin.last_totp_step:
        raise DomainError('MFA_REPLAY', '验证码已使用')
    admin.last_totp_step = verified_step
    admin.save(update_fields=['last_totp_step'])
    request.session.cycle_key()
    request.session['admin_id'] = str(admin.pk)
    request.session['session_version'] = admin.session_version
```

密码登录仅写 challenge，不能写正式 admin_id；每次认证比较 session_version。恢复命令只接受本地交互，重置 MFA 时写审计、递增版本。Cookie/CSRF 默认按规格设置；生产白名单不替代登录。

- [ ] **Step 4: 运行完整 P1 测试、Django check、迁移检查和秘密扫描。** `uv run --project backend pytest -c backend/pyproject.toml backend/tests -q`；确认 tests 无 SDK/SSH 实际调用。
- [ ] **Step 5: 提交 `feat: secure private administrator sessions and recovery`，进度记录 P1 门禁。**

## P1 完成门禁

- [ ] 新库从零 migrate 成功；唯一管理员的 PostgreSQL 并发约束通过。
- [ ] 正常登录与所有 session/MFA/CSRF 失败路径通过；无公开注册路由。
- [ ] control/subscription 密钥域、AAD、轮换旧版本解密和脱敏测试通过。
- [ ] archive 不入索引，不被源码边界测试扫描；Shop 未变更；所有实际命令与结果写入 progress。
