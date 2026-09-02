# Functional Evaluation V1

This suite exercises ten deterministic LearningLoop scenarios without real model calls. It measures
functional correctness, final structured artifacts, recovery, state integrity, idempotency and owner
isolation. It is not a model-quality benchmark or a production load test.

Run from the repository root:

```powershell
conda run --no-capture-output -n learningloop python evaluations/run_functional_v1.py
```

Generated artifacts are written to `evaluations/results/functional-v1.json` and
`evaluations/results/functional-v1.md`. The JSON includes every case result, errors, environment and
the runner SHA-256 so resume claims can be traced to one concrete evaluation version.

## Agent 指标测量

`measure_agent_metrics.py` 读取运行记录并输出 Agent 角色路由、Flash 调用占比和上下文边界数据：

```powershell
conda run --no-capture-output -n learningloop python evaluations/measure_agent_metrics.py --data-dir data --session-id <session-id>
```

上下文对比使用固定的 UTF-8 字节估算，仅用于相对比较；Pro-only 成本基线未提供时，成本差异保持
`null`。脚本不会把缺失的 usage、价格或基线解释为 0 或免费。

## 简历指标冻结评测

真实模型指标使用固定的 10 个路由场景和 3 组上下文对照：

```powershell
conda run --no-capture-output -n learningloop python evaluations/run_resume_metrics.py --live
```

结果写入 `evaluations/results/resume-metrics-v1.json` 和对应 Markdown 摘要。该命令会产生真实模型调用，默认不加 `--live` 时拒绝执行。
