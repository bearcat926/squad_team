# Squad Runtime Phase 0-6 — 外部验收审核提示词

> 将以下内容完整复制给你要使用的模型。压缩包附件：`phase0-6-evidence.zip`（22KB）

---

## 审核任务

你是一位资深软件质量专家。请对 Squad Runtime Phase 0-6 进行独立验收审核，基于压缩包中的证据材料，判断是否通过。

---

## 项目背景

**项目**：Squad Runtime — 本地单用户多智能体 Runtime，Python/FastAPI/SQLite + Node/React 前端。

**Phase 0-6 范围**：从 MVP 到 9 个真实场景配置的全链路验证，包括：
- 核心 Runtime（create_run / create_node / dispatch / gate_engine / analytics / export / archive）
- 前端构建（Node/React build/test/lint）
- 9 个场景配置：static_frontend_mvp, node_react_project, python_backend, fullstack_demo, multi_file_refactor, bugfix, security_fix, symlink_heavy_repository, archived_replay
- Rate limiter（rate_limiter.py + impl.py 更新）
- 9 个 strict gates

**声明基线**：
- 测试: 253 passed, 4 skipped
- 覆盖率: 92.73%（门槛 90%）
- Ruff / Black / MyPy: 0 errors
- codebase-memory: 6125 nodes / 11630 edges, indexed

---

## 证据材料（压缩包内文件）

| 压缩包内路径 | 大小 | 说明 |
|-------------|------|------|
| `README.md` | — | 文件清单和基线数据 |
| **data/summary-phase6.json** | 1.4KB | 运行摘要：agentCount=10, passRate=1.0, 9 gate PASS, 9 scenarioProfiles, lint/test/build exitCode=0 |
| **data/FULL_DATA_LOG-phase6.json** | 62KB | 全量 event/node/gate/agentResult 原始数据 |
| **data/replay-state-phase6.json** | 1.4KB | 回放状态快照 |
| **data/archive-run-875b5cebfd4a.json** | 60KB | Runtime archive_run 完整归档 |
| **data/archive-manifest.json** | 18KB | 归档文件清单 |
| **docs/phase0-6-acceptance-report.md** | 5.7KB | 已有验收报告（结论 PASS_WITH_RISKS） |

---

## 审核维度（请逐项回答）

### A. 运行数据完整性
1. 从 `summary-phase6.json` 中读取 passRate / gateStates / scenarioProfiles。是否有任何数据不一致或缺失？
2. `FULL_DATA_LOG-phase6.json` 是否包含 run_created / node_created / llm_session_started / llm_session_completed / agent_result_submitted / gate_decision 六类事件？
3. agentResults 数量是否 ≥ 10（每个 Agent 至少一条结果）？

### B. 质量门禁
4. 已有验收报告声明 253 passed / 4 skipped / 92.73% coverage。这些数字是否满足 Phase 验收标准（253 > 200, 92.73% > 90%）？
5. 已有验收报告声明 ruff/black/mypy 0 errors。是否有任何反证？

### C. 归档完整性
6. `archive-run-875b5cebfd4a.json` 是否可被 `json.loads()` 解析？
7. `archive-manifest.json` 中列出的文件数与 actual files 是否匹配？

### D. 风险和遗留
8. 已有验收报告标记为 PASS_WITH_RISKS，列出了真实 provider 工具循环、完整事件 hash chain、Windows symlink 三个后续风险。你的评估：这些风险是否应该阻塞 release？为什么？
9. 是否发现验收报告未提及的新问题？

### E. 整体判断
10. 综合以上，你的验收结论是什么？

---

## 输出格式

```markdown
# Phase 0-6 外部验收审核报告

## 一、数据完整性
[逐问回答 1-2-3]

## 二、质量门禁
[逐问回答 4-5]

## 三、归档完整性
[逐问回答 6-7]

## 四、风险评估
[逐问回答 8-9]

## 五、最终判断
- 结论: [PASS / PASS_WITH_RISKS / FAIL]
- 理由: [1-3 句话]
```
