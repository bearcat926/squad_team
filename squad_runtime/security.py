from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectInitialization:
    token: str
    token_created: bool


def initialize_project(squad_dir: Path) -> ProjectInitialization:
    squad_dir = Path(squad_dir)
    for child in ["artifacts", "checkpoints", "runs", "rules"]:
        (squad_dir / child).mkdir(parents=True, exist_ok=True)
    token_path = squad_dir / "token"
    if token_path.exists():
        return ProjectInitialization(token=token_path.read_text(encoding="utf-8").strip(), token_created=False)
    token = secrets.token_urlsafe(32)
    token_path.write_text(token, encoding="utf-8")
    return ProjectInitialization(token=token, token_created=True)


def read_token(squad_dir: Path) -> str:
    token_path = Path(squad_dir) / "token"
    if not token_path.exists():
        raise FileNotFoundError(f"Missing squad token: {token_path}")
    return token_path.read_text(encoding="utf-8").strip()


def rotate_token(squad_dir: Path) -> str:
    squad_dir = Path(squad_dir)
    squad_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    (squad_dir / "token").write_text(token, encoding="utf-8")
    return token


def token_matches(squad_dir: Path, provided: str | None) -> bool:
    if not provided:
        return False
    try:
        expected = read_token(squad_dir)
    except FileNotFoundError:
        return False
    return secrets.compare_digest(expected, provided)

