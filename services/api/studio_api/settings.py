"""Configuration from environment variables (see .env.example)."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _git_rev() -> str:
    env = os.environ.get("STUDIO_REVISION")
    if env:
        return env
    try:
        out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, timeout=3)
        rev = out.stdout.strip()
        if not rev:
            return "unversioned"
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"], capture_output=True, text=True,
                               timeout=3).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except Exception:  # noqa: BLE001
        return "unversioned"


@dataclass
class Settings:
    mode: str = field(default_factory=lambda: os.environ.get("STUDIO_MODE", "demo"))  # demo | live
    adapter_url: str = field(default_factory=lambda: os.environ.get("ADAPTER_URL", "http://127.0.0.1:8765"))
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", f"sqlite:///{(ROOT / 'data' / 'studio.db').as_posix()}"))
    fixtures_dir: Path = field(default_factory=lambda: Path(os.environ.get("FIXTURES_DIR", str(ROOT / "fixtures"))))
    initial_fixture: str = field(default_factory=lambda: os.environ.get("STUDIO_FIXTURE", "healthy"))
    subsystems: tuple[str, ...] = field(default_factory=lambda: tuple(
        s.strip() for s in os.environ.get("STUDIO_SUBSYSTEMS", "upper_body,navigation").split(",") if s.strip()))
    poll_interval_s: float = field(default_factory=lambda: float(os.environ.get("POLL_INTERVAL_S", "0.5")))
    eval_interval_s: float = field(default_factory=lambda: float(os.environ.get("EVAL_INTERVAL_S", "1.0")))
    record_heartbeat_s: float = field(default_factory=lambda: float(os.environ.get("RECORD_HEARTBEAT_S", "60")))
    telemetry_buffer: int = field(default_factory=lambda: int(os.environ.get("TELEMETRY_BUFFER", "600")))
    cors_origins: tuple[str, ...] = field(default_factory=lambda: tuple(
        os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")))
    llm_provider: str = field(default_factory=lambda: os.environ.get("LLM_PROVIDER", "none"))  # none|ollama|strands
    ollama_url: str = field(default_factory=lambda: os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: os.environ.get("OLLAMA_MODEL", ""))
    studio_revision: str = field(default_factory=_git_rev)
    run_loop: bool = True
