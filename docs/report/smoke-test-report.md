# Squad Runtime Provider 限流与 Scene F Smoke Test Report

## 执行摘要

本轮完成 provider 级限流与 429 归类机制，并重新执行 A-E fake_cli smoke 与 Scene F `claude_cli` 真实验收。

最终结论：**PASS**。

- Runtime public API、`NodeStatus`、`AgentResult` schema、GateEngine 规则均未变更。
- `claude_cli` 现在有内部 provider pacing：默认最小间隔 30 秒，429/529 默认冷却 30 秒，最多重试 1 次。
- 429 / rate limit / temporarily limiting requests 不再被归类为 `invalid_agent_result`，而是记录为 provider 层限流/阻塞。
- 本轮 Scene F 第二次完整重跑通过，10 个运行 Agent 全部产生真实 `claude_cli` AgentResult，4 个 Gate 全部 PASS。

## Verification Baseline

| 项目 | 结果 |
| --- | --- |
| `python -m py_compile scripts\smoke_dispatch.py scripts\acceptance\run_real_llm_acceptance.py squad_runtime\providers\rate_limiter.py` | PASS |
| `ruff check squad_runtime tests scripts` | PASS |
| `black --check squad_runtime tests scripts` | PASS |
| `mypy squad_runtime` | PASS |
| `python -m pytest tests -q` | 230 passed, 3 skipped |
| `python -m pytest tests -q --cov=squad_runtime --cov-report=term-missing` | 230 passed, 3 skipped, 93.51% coverage |
| codebase-memory index | indexed, 5369 nodes / 8743 edges |
| codebase-memory architecture query | non-empty |

## A-E fake_cli Smoke

| 场景 | 状态 | 说明 |
| --- | --- | --- |
| Scene A full-team smoke | PASS | 10 个 node 全部 PASS，4 个 gate 全部 PASS |
| Scene B edge cases | PASS | stale_advisory、cancel、retry、KeyError 路径通过 |
| Scene C gate dependencies | PASS | Gate 依赖子场景全部符合预期 |
| Scene D event + analytics | PASS | analytics 与 Runtime 事实一致 |
| Scene E contract tests | PASS | fail / blocked / low-confidence / empty-evidence / checkpoint mismatch 均符合预期 |

通过率：5 / 5。

## Scene F claude_cli

状态：**PASS**。

- Run: `run-d9561b5e3899`
- Provider: `claude_cli`
- Provider type: `real_llm`
- Provider identity verified: `true`
- AgentResult: 10 / 10
- Provider fallback: 0
- Synthetic dependency: 0
- Acceptance risks: `[]`
- Test Gate: PASS
- Code Review Gate: PASS
- Reality Checker Gate: PASS
- Release Gate: PASS

Scene F status artifact:

```json
{
  "scene": "F",
  "scenario": "scene-F",
  "status": "pass",
  "reason": "acceptance PASS, no risks",
  "provider": "claude_cli",
  "run_id": "run-d9561b5e3899",
  "coverage_percent": 93.51,
  "baseline_retry_needed": false,
  "initial_risks": [],
  "final_risks": []
}
```

## Provider 限流审计

本轮参考 `E:\Project\mimo2codex-plusplus` 的 cooldown-aware routing 思路，采用 30 秒冷却默认值。由于 Scene F 中每个真实 Claude dispatch 自身耗时均超过最小间隔，本次没有触发额外等待或 429 retry。

```json
{
  "provider_rate_limit_wait": 0,
  "provider_rate_limited": 0,
  "provider_blocked": 0,
  "provider_rate_limit_retry": 0,
  "agent_timeout": 0,
  "invalid_agent_result": 0
}
```

Provider usage:

```json
{
  "claude_cli": 10
}
```

## 发现与修复

| 编号 | 问题 | 处理 | 验证 |
| --- | --- | --- | --- |
| R-1 | `claude_cli` 高频 dispatch 可能触发 429，但 Runtime 原先没有 provider 级节流 | 新增 `ProviderRateLimiter`，支持 30 秒最小间隔、429/529 cooldown 和环境变量覆盖 | 新增 unit tests 覆盖 min interval、cooldown、env override |
| R-2 | CLI 非零退出中的 429 会被误归类为 `invalid_agent_result` | `LocalCliProvider` 先分类 stdout/stderr，429/rate limit 映射为 provider 限流事件和 `agent_unavailable` | 新增 acceptance tests 覆盖 429 与普通非零退出分流 |
| R-3 | Runner 遇到 provider 限流后没有合法重试路径 | acceptance runner 与 smoke runner 在 `provider_rate_limited` 后使用 `agent_unavailable -> ready` 重试一次 | 新增 runner tests 覆盖一次 429 后成功、超过重试限制失败 |
| R-4 | `smoke_dispatch.py` Scene F PASS 分支收尾变量未初始化 | 将 `risks = parsed["risks"]` 提前到 PASS/FAIL 分支之前 | Scene F 第二轮干净退出，状态为 PASS |

## Artifacts

当前主结果目录：`artifacts/smoke-test-iteration-4/`

- `FULL_DATA_LOG-scene-F.json`
- `archive-scene-F.json`
- `acceptance-report-scene-F.md`
- `acceptance-report-scene-F.stdout.txt`
- `acceptance-report-scene-F.stderr.txt`
- `analytics-scene-F.json`
- `provider-doctor.json`
- `scene-F-status-scene-F.json`
- `scene-F-status.json`
- `scene-F-run.stdout.txt`
- `scene-F-run.stderr.txt`

历史对照目录：`artifacts/smoke-test-iteration-3/`

- Scene F 已生成 PASS acceptance report，但旧版 `smoke_dispatch.py` 在最终状态写入阶段触发 `NameError`。该问题已由 R-4 修复，并通过 iteration-4 重跑验证。

## 剩余风险

1. 当前限流器是单实例内存级，不跨进程共享 cooldown；这符合 MVP 单 Server 假设。
2. 若 Claude CLI 长时间慢响应，Scene F 仍会耗时较长；本轮不改 provider timeout 策略。
3. Coverage 测试仍有既有 `ResourceWarning: unclosed database` 警告，但未导致测试失败，且不属于本轮限流范围。

## 最终结论

**PASS**

限流机制已实现并验证，A-E fake_cli smoke 全部通过，Scene F `claude_cli` 真实全员验收通过，Release Gate PASS。当前状态满足继续进行后续真实 LLM 验收与迭代的前置条件。
