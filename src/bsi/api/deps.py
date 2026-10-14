from __future__ import annotations

from bsi.config import Settings, get_settings


def settings_dep() -> Settings:
    return get_settings()
