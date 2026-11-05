# 发布与应用回退

## 发布

先在 registry 中构建并验证 backend/frontend 镜像，记录两个不可变 digest。服务器的受限配置文件指向这些 digest，然后执行：

```bash
deploy/scripts/release.sh \
  --version 0.13.0 \
  --digest sha256:<backend-image-digest> \
  --config /etc/xray/config.env \
  --compose deploy/compose/production.yml
```

`--digest` 必须与配置中的 backend 镜像完全一致，`--version` 必须与仓库 `VERSION` 一致。脚本不接受 tag-only 镜像。发布前的备份失败、迁移计划失败、worker 无法排空或迁移检查失败都会阻止镜像切换。

## GitHub 版本发布与前端热更新

向 `main` 合并后，在 `VERSION` 与前端包版本一致的提交上创建不可变标签
`v0.13.0`。`.github/workflows/release.yml` 会校验标签与版本、打包
`installer/`、生成 `SHA256SUMS`，并创建 GitHub Release。安装器远程入口和
`XRAY_INSTALLER_REF` 必须使用同一个标签；不要改成 `main` 或 `latest`。
当前仓库为 private，匿名 raw GitHub 下载会返回 `404`；若要让没有 GitHub
登录态的生产主机直接执行一行命令，需要先获得公开仓库或单独的公开安装器托管
授权。不能把个人访问令牌写进脚本、命令行参数、日志或 URL。

管理台前端使用同源 `HEAD /` 请求比较 `ETag`/`Last-Modified`。生产切换到新的
不可变 frontend 镜像后，已打开的管理台会提示刷新；这只代表浏览器静态包热更新，
不会替代数据库迁移、备份、worker drain 或 `release.sh` 的完整生产发布流程。

发布证据至少记录 Git commit/tag、两个镜像 digest、Compose config 摘要、备份 manifest、迁移计划、门禁结果和操作者审批。任何输出进入 `artifacts/acceptance/<version>/` 前都要脱敏。

## 回退

应用回退使用已验证的上一版本镜像配置：

```bash
deploy/scripts/rollback.sh \
  --version 0.5.0 \
  --config /etc/xray/previous-images.env \
  --compose deploy/compose/production.yml
```

回退脚本只排空 worker 并切换应用镜像，不调用 `pg_restore`、不反向迁移，也不修改撤销记录、Token tombstone、已失效凭据、云操作结果或安全事件。若上一版本无法读取当前 expand/contract schema，保持维护模式并停止，不允许以旧数据库覆盖当前库。

## 失败处理

- worker drain 超时：检查 Operation 和 provider request ID，完成对账后人工恢复 consumer 或重试发布。
- 迁移失败：保持旧应用或维护模式，保存错误和迁移状态；通过向前修复迁移处理。
- 新镜像健康检查失败：保持数据库原状，使用上一组 digest 执行应用回退。
- 撤销/云结果不明：保持 SecurityBarrier 关闭、节点隔离和 worker 云写禁用，按事故手册对账。

Git 层使用阶段标签或 `git revert <commit>`。禁止强推、硬重置和删除安全历史。
