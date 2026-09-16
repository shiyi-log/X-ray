# 密钥与凭据轮换

## 独立域

- Django signing key：只影响会话与签名，不用于业务密文。
- control master key：云凭据、SSH 和 MFA 控制域；不提供给订阅进程。
- subscription master key：订阅 payload；subscription reader 只持有此域。
- age recipient/identity：recipient 在备份端，identity 离机双份托管，不进入数据库备份。
- 数据库角色：owner 只用于迁移/恢复；admin、subscription reader、worker、outbox 各自独立口令。
- TLS、云 API、节点协议凭据分别轮换，不能用一次“全局换钥”掩盖未完成项。

## 常规轮换

1. 创建新 key version，保留旧解密 key，先验证所有密文都能读取。
2. 以 purpose 和 AAD 原样解密后重新加密，记录数量与失败对象，不记录明文。
3. 切换写入版本，跑前后端、订阅和 worker 回归。
4. 生成加密备份并验证新旧恢复路径。
5. 所有活动数据完成迁移且保留期满足后，另行审批退役旧 key。

数据库口令轮换通过 `database-bootstrap` 同步角色，不在 Compose 环境中传值。云凭据版本不可修改；创建并验证新版本后切换账号指针，旧版本保留作审计但禁止新操作。

## 恢复后轮换

恢复默认假设备份时点之后的所有秘密可能已失效。`rotate_after_restore` 只在 SecurityBarrier 已关闭、提供具体审批引用并输入 `INVALIDATE ALL RESTORED CREDENTIALS` 时运行。它永久撤销恢复出的 token、访问身份与节点凭据，并保持所有节点维护；不会凭空声称云密钥或远程节点已完成轮换。

恢复开放前必须逐项取得新证据：管理员会话版本更新、所有旧订阅 410、节点新凭据接受/旧凭据拒绝、云账号新身份验证、SSH host key 仍匹配、离机账本追平。缺任一项就保持 `MAINTENANCE`。
