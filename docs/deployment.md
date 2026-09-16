# 独立部署

## 边界

生产包面向独立 Debian 12 主机。它不读取 Shop、同级仓库、`archive/` 或开发机环境。当前仓库只完成本地 Compose 解析、镜像构建和隔离演练；在没有服务器、域名、证书和授权时，不代表已经上线。

Compose 只由 gateway 暴露端口。管理入口绑定私有地址并受 CIDR allowlist 限制；订阅入口只接受 `GET/HEAD /s/<43-char-token>`。PostgreSQL、Redis、API、worker 和前端不直接发布宿主端口。未知 Host、管理路径出现在订阅域名、伪造 Forwarded 头或其他路径都返回 404/拒绝。

## 主机准备

1. 安装 Docker Engine 与 Compose plugin，固定服务器时钟并启用系统审计。
2. 创建只供 X-ray 使用的数据、秘密、TLS、备份暂存和发布配置目录；不要复用其他项目数据库或 Redis。
3. 从 `deploy/compose/config.example.env` 生成服务器侧非秘密配置。两个应用镜像必须是 registry 地址加 `@sha256:<64 hex>`。
4. 根据 `deploy/secrets.example.md` 挂载秘密文件。私钥和口令文件不得对 other 可读。
5. 先运行只读预检：

```bash
deploy/scripts/preflight.sh \
  --config /etc/xray/config.env \
  --compose deploy/compose/production.yml
```

## 服务权限

| 服务 | 网络 | 密钥/角色 |
| --- | --- | --- |
| `admin-api` | control、data、queue | admin DB、control、subscription |
| `subscription-api` | public-app、data | subscription reader DB、subscription only |
| `worker` | data、queue | worker DB、control、subscription、cloud |
| `outbox-dispatcher` | data、queue | outbox DB、Django signing only |
| `security-ledger-dispatcher` | data、离机账本挂载 | outbox DB、Django signing only |
| `frontend` | control | 无业务秘密 |
| `gateway` | edge、control、public-app | TLS key only |

容器使用只读 rootfs、固定非 root UID、drop all capabilities 和 `no-new-privileges`。数据库迁移和角色同步只存在于 `release` profile，不作为常驻进程。subscription reader 明确不能读取云凭据表或写审计表。

## 首次发布

发布脚本要求先完成一次加密备份，即使新库为空也保留 manifest。脚本顺序是预检、备份、角色引导、迁移计划、worker drain、迁移、权限刷新、迁移检查、应用切换。worker drain 超时会停止发布并保持消费暂停，不能把强杀后的未知操作当成成功。

具体命令和回退步骤见 [release.md](release.md)。数据库备份和隔离恢复见 [backup-recovery.md](backup-recovery.md)。
