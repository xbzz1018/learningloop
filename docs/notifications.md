# 定时学习提醒

[返回首页](../README.md)

服务运行期间，调度器按会话设置发送今日计划和晚间复盘。默认时区为 `Asia/Shanghai`，时间分别为 08:30 和 20:30。

## 配置 SMTP

在项目自己的 `.env` 中填写以下参数，重启服务后生效：

| 参数 | 用途 |
| --- | --- |
| `LEARNINGLOOP_SMTP_HOST` | 邮件服务地址 |
| `LEARNINGLOOP_SMTP_PORT` | 端口，默认 `465` |
| `LEARNINGLOOP_SMTP_USERNAME` | SMTP 用户名 |
| `LEARNINGLOOP_SMTP_PASSWORD` | SMTP 密码或授权码 |
| `LEARNINGLOOP_SMTP_SENDER` | 发件人地址 |
| `LEARNINGLOOP_SMTP_USE_SSL` | 默认 `true`；用于 SSL 连接 |
| `LEARNINGLOOP_SMTP_USE_TLS` | 默认 `false`；使用 STARTTLS 时改为 `true`，同时关闭 SSL 并修改端口 |

未配置 SMTP 时，消息写入 `data/notifications/outbox/`，便于查看生成内容。

## 启用会话提醒

先创建学习会话，在「通知设置」填写收件邮箱、时区、早间计划时间与晚间复盘时间。勾选「启用定时邮件」并保存，再点击「发送测试邮件」检查投递。

调度器每 30 秒检查到期提醒。同一会话、日期和提醒类型只投递一次；失败最多尝试 3 次，投递记录显示在通知页面。服务重启后可补发 6 小时内的到期任务。

## 手动运行

从仓库根目录、已激活的项目环境运行：

```powershell
learningloop notifications run-once
```

这次检查按会话时区处理已到时间且仍在补发窗口内的提醒。需要立即运行时使用 `learningloop notifications run-once --force`，它会跳过到期时间和补发窗口的检查，可能提前生成当天的早间计划和晚间复盘。生成内容时可能调用模型，已成功投递的同一提醒不会重复发送。
