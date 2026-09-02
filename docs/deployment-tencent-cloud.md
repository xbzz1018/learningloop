# 腾讯云 CVM 私有部署

该部署面向实验室少量成员使用，不开放注册，也不提供企业组织、OAuth 或复杂 RBAC。
Caddy 只负责 HTTPS 和反向代理，LearningLoop 应用负责轻量账号、会话和数据隔离。

## 1. 服务器准备

在腾讯云 CVM 上安装 Docker Engine 和 Compose 插件，安全组只开放：

- `22/tcp`：仅允许管理员办公网络；
- `80/tcp`、`443/tcp`：Caddy 自动签发和续期证书。

应用容器只通过 Compose 内部网络暴露 `8765`，不直接绑定公网端口。
应用容器使用非 root 用户运行；每个 HTTP 请求返回 `X-Request-ID`，用于关联日志、Run 和模型调用。

## 2. 配置

复制 `.env.example` 为 `.env`，填写官方 DeepSeek Key、SMTP（可选）和：

```text
LEARNINGLOOP_DOMAIN=learn.example.com
LEARNINGLOOP_AUTH_ENABLED=true
LEARNINGLOOP_AUTH_COOKIE_SECURE=true
```

密钥只通过服务器环境变量注入，不写入镜像、日志、SQLite 或前端。

## 3. 启动和创建账号

```powershell
docker compose -f docker-compose.tencent.yml up -d --build
docker compose -f docker-compose.tencent.yml exec app learningloop users create admin
```

创建命令会交互式读取密码。首次创建的账号会自动接管迁移前的本地数据。

## 4. 备份和恢复

备份使用 SQLite Backup API，不直接复制运行中的 `-wal` 文件：

```powershell
docker compose -f docker-compose.tencent.yml exec app learningloop backup create --output /data/backups/learningloop-$(Get-Date -Format yyyyMMdd).db
```

恢复前停止应用，执行恢复并检查 `PRAGMA integrity_check`，再重新启动：

```powershell
docker compose -f docker-compose.tencent.yml stop app
docker compose -f docker-compose.tencent.yml run --rm app learningloop backup restore --input /data/backups/learningloop-20260902.db --confirm
docker compose -f docker-compose.tencent.yml up -d app
```

建议由腾讯云主机 Cron 每日调用备份命令，并将备份复制到独立对象存储；本项目不把对象存储凭据写入应用。

## 5. 验收

- 未登录访问工作台返回登录页，API 返回 `401`；
- 两个账号只能看到自己的会话、计划、通知和用量；
- 容器重启后会话、ActionCard、Checkpoint 和学习状态仍在；
- `/health` 返回 `0.3.1` 和脱敏 Provider 状态；
- 官方 API 调用、Token、缓存和费用估算能在用量页复算；
- SMTP 失败不会回滚学习状态。
