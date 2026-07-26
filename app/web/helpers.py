"""Shared helpers for Panoptes web + CLI."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent.parent
EXPORTS_DIR = ROOT / "exports"
ENV_PATH = ROOT / ".env"


def load_env(path: Path | None = None) -> None:
    env_path = path or ENV_PATH
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip())


def env_get(*keys: str, default: str = "") -> str:
    for key in keys:
        val = os.environ.get(key)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return default


def update_env(key: str, value: str) -> None:
    lines: list[str] = []
    found = False
    if ENV_PATH.exists():
        with open(ENV_PATH, encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith(key + "="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.environ[key] = value


def delay_range(fallback: tuple[float, float] = (1.0, 2.5)) -> tuple[float, float]:
    try:
        d_min = float(env_get("PANOPTES_DELAY_MIN", default=str(fallback[0])))
        d_max = float(env_get("PANOPTES_DELAY_MAX", default=str(fallback[1])))
        return (d_min, d_max) if d_max >= d_min >= 0 else fallback
    except ValueError:
        return fallback


PLATFORM_SCRAPERS = {
    "instagram": ("app.scrapers.instagram", "scrape_profile_no_login", (1.5, 4.0)),
    "tiktok": ("app.scrapers.tiktok", "scrape_tiktok_profile", (2.0, 5.0)),
    "linkedin": ("app.scrapers.linkedin", "scrape_linkedin_profile", (3.0, 6.0)),
    "github": ("app.scrapers.github", "scrape_profile", (0.5, 1.5)),
    "youtube": ("app.scrapers.youtube", "scrape_channel", (1.0, 2.5)),
    "twitch": ("app.scrapers.twitch", "scrape_profile", (0.5, 1.5)),
    "linktree": ("app.scrapers.linktree", "scrape_linktree", (0.5, 1.5)),
    "pinterest": ("app.scrapers.pinterest", "scrape_profile", (1.0, 2.5)),
}


def get_scraper(platform: str):
    if platform not in PLATFORM_SCRAPERS:
        raise ValueError(f"Unsupported platform: {platform}")
    module_name, func_name, delays = PLATFORM_SCRAPERS[platform]
    import importlib

    module = importlib.import_module(module_name)
    return getattr(module, func_name), delays
