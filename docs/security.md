# 安全边界

- API Key 和 SMTP 密码只通过环境变量或 Secret 注入；
- Runtime、Skill 和搜索结果都将用户输入视为不可信；
- 模型没有文件系统、SQLite 或通用 Shell 权限；
- 状态写入只能通过 Typed Tool、Pydantic 校验和 ActionCard；
- Trace 和日志删除 prompt、answer、query 等正文；
- 腾讯云 profile 使用 Argon2id、HttpOnly/Secure/SameSite Cookie；
- 不开放注册，不保存原始密码，不实现 OAuth；
- Caddy 只代理 HTTPS，应用端口不直接暴露公网。

账号隔离是实验室规模的数据边界，不等价于企业级租户、组织或 RBAC 系统。
