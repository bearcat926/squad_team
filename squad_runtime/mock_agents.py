from __future__ import annotations

import asyncio
from typing import Any, Callable


Callback = Callable[[dict[str, Any]], None]


class MockAgent:
    def __init__(self, agent_id: str, agent_type: str, config: dict[str, Any] | None = None):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.config = config or {}

    async def execute(self, task_input: dict[str, Any], callbacks: dict[str, Callback]) -> dict[str, Any]:
        failure_mode = self.config.get("failure_mode", "success")
        if failure_mode == "timeout":
            await asyncio.sleep(float(self.config.get("timeout_sleep_sec", 0.01)))
            raise TimeoutError("mock timeout")
        if failure_mode == "unavailable":
            raise RuntimeError("mock unavailable")

        callbacks["on_heartbeat"]({"agentId": self.agent_id, "status": "busy"})
        steps = int(self.config.get("steps", 3))
        delay = float(self.config.get("step_delay_sec", 0))
        for step in range(steps):
            if delay:
                await asyncio.sleep(delay)
            callbacks["on_progress"]({"agentId": self.agent_id, "step": step + 1, "totalSteps": steps})
            callbacks["on_heartbeat"]({"agentId": self.agent_id, "status": "busy"})

        if failure_mode == "invalid_schema":
            return {"agent_id": self.agent_id, "status": "pass"}

        status = {
            "success": "pass",
            "fail": "fail",
            "blocked": "blocked",
        }.get(failure_mode, "pass")
        return {
            "taskNodeId": task_input["taskNodeId"],
            "agentId": self.agent_id,
            "status": status,
            "summary": f"Mock {self.agent_type} result: {status}",
            "evidence": [{"type": self.agent_type, "content": "mock evidence"}],
            "artifacts": [],
            "risks": [],
            "nextActions": [],
            "confidence": 0.9 if status == "pass" else 0.3,
            "workedAgainstCheckpoint": task_input["checkpoint"],
            "agentContractVersion": "v1",
        }


class MockAgentFactory:
    AGENT_TYPES = {"backend", "frontend", "test", "review"}

    @classmethod
    def create(cls, agent_type: str, config: dict[str, Any] | None = None) -> MockAgent:
        if agent_type not in cls.AGENT_TYPES:
            raise ValueError(f"Unknown mock agent type: {agent_type}")
        cfg = config or {}
        return MockAgent(
            agent_id=cfg.get("agent_id", f"mock-{agent_type}"),
            agent_type=agent_type,
            config=cfg,
        )
