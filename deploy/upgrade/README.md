# 在线升级主机执行器

管理 API 只写升级请求，不拥有 Docker socket、主机命令执行权限或云权限。
主机 root 定时器每 15 秒读取请求，选择运维人员预置的完整发布快照和不可变
镜像，依次导出安全账本、执行现有备份与 release.sh，再写回有限的状态信息。
不会从浏览器接收 URL、镜像地址、脚本或文件路径，也不会自动下载执行代码。

目录权限必须在启动新版本 admin-api 前配置：

```sh
sudo install -d -o root -g root -m 0755 /var/lib/xray/upgrade
sudo install -d -o 10001 -g 10001 -m 0700 /var/lib/xray/upgrade/requests
sudo install -d -o root -g root -m 0755 /var/lib/xray/upgrade/results
sudo install -d -o root -g root -m 0700 /var/lib/xray/upgrade/releases
sudo install -d -o root -g root -m 0700 /var/lib/xray/upgrade/history
```

运维人员先把已审查的发布 `deploy/`、`installer/` 和 `VERSION` 放入
`/var/lib/xray/upgrade/releases/<version>/source/`。发布目录、manifest 和快照
所有目录及文件均必须 root 所有，不允许组或其他用户写入，不允许符号链接
或硬链接。源快照必须包含完整 deploy 目录，而不只是 release.sh。镜像应先
推入受控 registry 并通过不可变 digest 拉取验证。不能把下载、构建或 registry
凭据放进目录。

`releases/<version>/manifest.json` 使用如下结构（替换为真实校验后的摘要）：

```json
{
  "schema_version": 1,
  "version": "0.14.9",
  "backend_image": "127.0.0.1:15000/xray/backend@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "frontend_image": "127.0.0.1:15000/xray/frontend@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

`catalog.json` 由 root 管理，0644，只列可在界面选择的版本：

```json
{
  "schema_version": 1,
  "releases": [
    {
      "version": "0.14.9",
      "published_at": "2026-11-14T00:00:00Z",
      "notes": "经过校验的版本说明"
    }
  ]
}
```

先运行 `/usr/bin/python3 /opt/xray/deploy/upgrade/runner.py` 验证队列读取无误，
再安装当前目录的 service/timer 到 `/etc/systemd/system/`，执行
`systemd-analyze verify`、`systemctl daemon-reload` 和
`systemctl enable --now xray-manager-upgrade.timer`。这是 root 系统服务，必须在
用户授权的生产主机上安装；本地测试不应安装系统服务。

界面通过管理员登录、CSRF、近期 step-up 和 UUID Idempotency-Key 提交
`requests/<uuid>.json`。root 执行器独占 `.runner.lock`；相同 job 不会重执行，
终态写入 `results/<uuid>.json` 后保留请求作为幂等记录。请求有效期为 90 分钟，
使用 aware UTC 时间，在 `now >= created_at + 90 minutes` 时拒绝，最多容忍
60 秒未来时钟偏差。系统重启发现旧 RUNNING 结果时标记 FAILED /
ROLLBACK_REQUIRED / UPGRADE_INTERRUPTED，等待人工读回实际服务，不自动重试
可能已经执行的数据库迁移。

每次升级前在 `history/<uuid>.env` 保存当前配置（root 0600），导出安全账本
快照，再调用预置 source 的 release.sh。发布脚本执行预检、加密数据库备份、
worker 排空、向前迁移、API 健康校验与后台服务启动。执行器不保存或公开原始
命令输出、异常或日志。界面只收到状态、阶段、固定错误码与时间戳。

release.sh 返回失败时，只恢复前一份配置，结果为 FAILED /
ROLLBACK_REQUIRED，不声称服务已自动恢复。运维人员必须按历史镜像和生产
读回确定应用回退。数据库、撤销墓碑、安全事件、凭据和云操作状态不反向
恢复。预置下一版本应使用新目录；不要覆盖已经执行过的发布快照。
