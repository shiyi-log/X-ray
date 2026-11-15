# 公网 HTTPS 管理入口

本机部署可让管理员和订阅域名共用公网 443，通过主机 Nginx 的 stream
SNI 分流到既有网关 TLS 监听，不改变管理员认证、CSRF、近期身份验证或
目标绑定预览。公网入口必须经任务级授权后配置。

前置条件：主机 Nginx 支持 stream_ssl_preread，stream 上下文有项目配置
include，两个域名解析到该主机，现有证书覆盖两个域名。检查公网 443
的归属和现有站点，不可占用其他项目监听。

1. 备份 `/etc/xray/config.env` 到 root 所有、0600 的受控 history 文件，
   不将内容打印或复制进仓库。持有在线升级 runner 的 `.runner.lock` 并
   确认没有待执行升级，避免网关变更与升级同时执行。
2. 将 `public-sni.conf.template` 的三个明确占位符替换为部署的管理员
   域名、订阅域名和主机公网接口对应的本地 IPv4。保留 Nginx 的
   `$ssl_preread_server_name`、`$xray_tls_backend` 变量，不使用无变量
   白名单的 envsubst。主机 stream 配置不保存私钥、不记录请求。
3. 将渲染结果安装到主机的 stream include 目录，先执行主机 `nginx -t`。
   公网监听使用精确接口 IP，不使用 `0.0.0.0`，避免和 loopback443 冲突。
4. 在现有环境配置中将 `XRAY_SUBSCRIPTION_BIND_IP` 改为 `127.0.0.1`，
   保留 `XRAY_ADMIN_BIND_IP=127.0.0.1` 及管理 CIDR。只重新创建
   gateway 服务，等待健康成功后重载主机 Nginx。切换会短暂重连。
5. 公网443按 SNI 将管理员域名转发到 loopback8443，将订阅域名转发到
   loopback443；未知 SNI 拒绝。TLS 在既有网关终止，继续使用现有证书
   续期流程。不要修改已经执行过的不可变发布快照。
6. 检查两个域名的严格 TLS、普通浏览器登录页、未登录 API 拒绝、正常
   登录和会话、CSRF/外域拒绝、在线升级和删除操作的近期验证及预览。
   用无副作用的拒绝请求验证，不提交真实升级或真实节点删除。

主机 stream 配置独立于应用发布快照；升级 runner 更新环境文件中的
镜像项和安全快照路径，保留其他配置，包括 loopback bind 值。后续发布仍需检查新的 Compose 端口约定
兼容，并验证两个公网入口；本次不以实际再升级来验证持久性。

回退时先移除本项目新增的 stream include，主机 `nginx -t` 成功后重载
以释放公网443，再将配置中的订阅 bind 恢复为变更前值，只重建 gateway
并验证订阅健康。恢复配置时只恢复本次 bind 字段，避免覆盖后续镜像或
其他设置。应用、数据库、撤销、安全事件和云操作历史不回退。

当前生产入口为 `https://admin.xray.ai163.cc`，应用版本仍为 0.14.10。
管理8443和订阅后端443均只监听服务器 loopback，日常访问无需本机隧道。
