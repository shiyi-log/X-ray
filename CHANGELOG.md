# 变更记录

## 0.3.0 - 2026-09-17

- 增加 PostgreSQL 配额预留、UUID 幂等、危险操作预览、durable outbox、worker lease/fencing、取消与重复投递终态处理。
- 增加双云 Fake 共用的节点创建/对账/隔离生命周期；未知云写入转入 `NEEDS_RECONCILIATION`，防火墙 ACK 不再等同隔离成功。
- 固定 Xray-core `v26.3.27` 及三平台官方 SHA-256，提供仅接受离线固定包的安装、验证和 generation-safe 原子配置脚本。
- 增加 Paramiko 指纹钉扎传输、五协议能力矩阵、socks5h 探测，以及真实本地 Xray 五协议链路验收。
- 66 项后端/安装器测试、Ruff、ShellCheck、迁移漂移、边界和秘密扫描通过；真实云、远程 SSH 和公网探测未执行。

## 0.0.1 - 2026-09-17

- 建立 `codex/xray-manager` 实施分支和 `v0.0.0-baseline` 可回退基线。
- 增加仓库内 `skills/xray-manager` 专属技能、版本记录和验收台账约定。
- 修正审计迁移的可交换用户依赖，并让边界测试只扫描项目源码。
- P1-P6 业务实现尚未完成；真实云、远程 SSH、生产部署和资源删除未执行。

## 0.1.0 - 2026-09-17

- 完成唯一超级管理员、Argon2 密码、TOTP 首次绑定/验证、一次性恢复码和服务器会话。
- 增加 CSRF JSON 错误、会话版本撤销、step-up、恢复命令和身份审计脱敏。
- `SecretStore` 支持 control/subscription purpose、AAD 绑定和密钥版本保留。
- 双云、节点、订阅、前端和真实外部验收仍未完成。

## 0.2.0 - 2026-09-17

- 增加不可变云凭据版本、云身份验证/轮换和只写不读管理 API。
- 锁定 AWS Lightsail 与阿里云 SWAS SDK，并交付显式 client、拒绝默认写入的适配器契约。
- 增加能力矩阵、MutationPermit/authorizer、SDK 错误脱敏和默认断网门禁。
- 30 项后端测试、迁移漂移、Ruff、边界和秘密扫描通过；真实云验证未执行。

## 版本规则

- `0.x` 表示尚未承诺生产兼容性的开发版本。
- 每个阶段完成后创建带注释 Git 标签；版本正文与 `docs/version-record.md` 同步。
- 回退优先使用阶段标签或反向提交，不重写共享历史。
