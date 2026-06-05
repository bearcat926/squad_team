from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class AgentProfile:
    agent_id: str
    display_name: str
    role: str
    profile_version: str
    provider: str
    output_contract: Literal["LeadDecisionChangeSet", "AgentResult"]
    allowed_tools: tuple[str, ...] = field(default_factory=tuple)
    allowed_read_paths: tuple[str, ...] = field(default_factory=lambda: ("**/*",))
    allowed_write_paths: tuple[str, ...] = field(default_factory=tuple)
    forbidden_paths: tuple[str, ...] = (".squad/*", ".squad/**", "**/.squad/*", "**/.squad/**")
    fallback_provider: str | None = None
    fallback_mode: Literal["none", "manual", "automatic"] = "none"


class AgentRegistry:
    def __init__(self, version: str, agents: list[AgentProfile]):
        self.version = version
        self._agents = {agent.agent_id: agent for agent in agents}

    @classmethod
    def default(cls) -> AgentRegistry:
        common_read = ("**/*",)
        safe_forbidden = (".squad/*", ".squad/**", "**/.squad/*", "**/.squad/**")
        return cls(
            "registry-v1",
            [
                AgentProfile(
                    "squad-lead",
                    "Squad Lead",
                    "Product decisions and execution orchestration",
                    "profile-v1",
                    "claude_cli",
                    "LeadDecisionChangeSet",
                    ("read", "log", "dispatch"),
                    common_read,
                    (),
                    safe_forbidden,
                    fallback_provider="fake_cli",
                    fallback_mode="manual",
                ),
                AgentProfile(
                    "rapid-prototyper",
                    "Rapid Prototyper",
                    "Prototype validation",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write"),
                    common_read,
                    ("project-docs/**", "prototypes/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "software-architect",
                    "Software Architect",
                    "Architecture and ADRs",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write"),
                    common_read,
                    ("project-docs/**", "docs/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "ui-designer",
                    "UI Designer",
                    "UX, visual design, accessibility specs",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write"),
                    common_read,
                    ("project-docs/**", "docs/**", "styles.css"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "backend-architect",
                    "Backend Architect",
                    "Backend implementation and data services",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write", "test"),
                    common_read,
                    ("**/*.py", "**/*.json", "tests/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "frontend-developer",
                    "Frontend Developer",
                    "Frontend implementation",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write", "test"),
                    common_read,
                    ("**/*.html", "**/*.css", "**/*.js", "tests/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "test-engineer",
                    "Test Engineer",
                    "Testing, QA evidence, regression validation",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "write", "test", "browser"),
                    common_read,
                    ("tests/**", "project-docs/**", "reports/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "code-reviewer",
                    "Code Reviewer",
                    "Code review and findings",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "test"),
                    common_read,
                    ("reports/**", "project-docs/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "reality-checker",
                    "Reality Checker",
                    "Release readiness and veto",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "test"),
                    common_read,
                    ("reports/**", "project-docs/**"),
                    safe_forbidden,
                ),
                AgentProfile(
                    "git-workflow-master",
                    "Git Workflow Master",
                    "Release execution and archive",
                    "profile-v1",
                    "claude_cli",
                    "AgentResult",
                    ("read", "git", "archive"),
                    common_read,
                    ("release/**", "reports/**"),
                    safe_forbidden,
                ),
            ],
        )

    def get(self, agent_id: str) -> AgentProfile:
        try:
            return self._agents[agent_id]
        except KeyError as exc:
            raise KeyError(f"Unknown agent: {agent_id}") from exc

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list_agents(self) -> list[AgentProfile]:
        return list(self._agents.values())

    def with_provider_override(
        self,
        agent_id: str,
        provider: str | None = None,
        fallback_provider: str | None = None,
        fallback_mode: Literal["none", "manual", "automatic"] | None = None,
    ) -> AgentRegistry:
        agents = []
        for agent in self.list_agents():
            if agent.agent_id != agent_id:
                agents.append(agent)
                continue
            agents.append(
                AgentProfile(
                    agent.agent_id,
                    agent.display_name,
                    agent.role,
                    agent.profile_version,
                    provider or agent.provider,
                    agent.output_contract,
                    agent.allowed_tools,
                    agent.allowed_read_paths,
                    agent.allowed_write_paths,
                    agent.forbidden_paths,
                    fallback_provider if fallback_provider is not None else agent.fallback_provider,
                    fallback_mode if fallback_mode is not None else agent.fallback_mode,
                )
            )
        return AgentRegistry(self.version, agents)

    def snapshot(self) -> dict[str, object]:
        return {
            "agentRegistryVersion": self.version,
            "agents": [agent.__dict__ for agent in self.list_agents()],
        }
