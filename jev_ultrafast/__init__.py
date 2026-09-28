"""Jev chooses an observed action. Code owns execution."""

import os
from pathlib import Path


def load_environment():
    """Load local settings before Browser Harness reads its import-time configuration."""
    path = Path.cwd() / ".env"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_environment()


def __getattr__(name):
    if name == "Agent":
        from .agent import Agent

        return Agent
    if name == "Browser":
        from .browser import Browser

        return Browser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["Agent", "Browser"]
