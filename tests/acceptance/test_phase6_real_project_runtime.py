from __future__ import annotations

from pathlib import Path

from scripts.phase6_real_project_runtime import run_phase6_real_project_runtime


def test_phase6_real_project_runtime_produces_artifacts_and_strict_gate_pass(tmp_path: Path) -> None:
    summary = run_phase6_real_project_runtime(tmp_path / "phase6")

    assert summary["passRate"] == 1.0
    assert summary["gateStates"]["release_gate"] == "pass"
    assert summary["scenarioProfiles"] == [
        "static_frontend_mvp",
        "node_react_project",
        "python_backend",
        "fullstack_demo",
        "multi_file_refactor",
        "bugfix",
        "security_fix",
        "symlink_heavy_repository",
        "archived_replay",
    ]
    assert Path(summary["fullDataLog"]).exists()
    assert Path(summary["archiveManifest"]).exists()
    assert Path(summary["replayState"]).exists()
    assert summary["nodeReactBuildExitCode"] == 0
    assert summary["nodeReactTestExitCode"] == 0
    assert (Path(summary["projectRoot"]) / "frontend" / "index.html").exists()
    assert (Path(summary["projectRoot"]) / "node-react" / "app.mjs").exists()
    assert (Path(summary["projectRoot"]) / "backend" / "app.py").exists()
    assert (Path(summary["projectRoot"]) / "reports" / "review-fact.md").exists()
