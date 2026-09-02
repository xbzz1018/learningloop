# 当前限制

- 单实例、单 Worker；
- 账号为轻量私有账号，不支持公开注册、OAuth、组织和复杂角色；
- SQLite 适合个人和小规模实验室，不作为高并发多租户数据库；
- 官方 DeepSeek 价格仅用于估算，中转站真实账单可能不可得；
- OpenTelemetry 导出为可选能力，本地 JSONL/SQLite 才是审计来源；
- 不支持视觉、多模态、RAG、向量数据库、MCP、短信和通用 Shell；
- Skill 不会由模型自动修改，任何 Skill 变更必须由开发者审核。
