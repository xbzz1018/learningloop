# 恢复和幂等

## 稳定阶段

每个 Run 依次写入 `received`、`context_ready`、`model_completed`、`effect_applied`、`awaiting_action` 和 `completed` Checkpoint。进程在模型流中退出时，不重放半段文本，而是从最近稳定阶段重新执行。

## 工具副作用

会修改学习状态的工具先写入 `tool_effects` 保留记录，成功后写入结构化结果。重复请求使用相同的 session、来源消息、工具和参数哈希，已完成效果直接返回，不再次修改文件。

如果进程在副作用完成、账本标记前退出，效果会保持 `reserved`，后续运行不会盲目重试；需要通过错误记录或人工处理确认，避免重复记账。

## SQLite 备份

创建备份时给文件名加上时间，避免覆盖上一份。

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupFile = "data/backups/learningloop-$stamp.db"
learningloop backup create --output $backupFile
```

命令返回备份路径和 `integrity` 检查结果。恢复前先停止正在使用该数据库的 `learningloop serve` 进程或应用容器，再把 `$backupFile` 设为要恢复的文件路径。

```powershell
learningloop backup restore --input $backupFile --confirm
```

恢复会覆盖当前配置的数据目录中的 `learningloop.db`，写入后执行 `PRAGMA integrity_check`。确认结果为 `ok` 后再启动服务。
