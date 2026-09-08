"""Provider presets, availability detection, and per-user provider resolution.

Provider kinds:
  mock               built-in offline rule-based provider (always available)
  openai_compatible  OpenAI / Ollama / LM Studio / vLLM / any compatible endpoint
  cli                local agent CLIs (Claude Code, Codex, opencode) run non-interactively

Users pick provider + model + base_url + key in Settings (stored server-side in
user_preferences; keys are never returned to the browser).
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models import User, UserPreference
from .provider import AIProvider, CliProvider, MockProvider, OpenAICompatibleProvider


@dataclass(frozen=True)
class Preset:
    id: str
    label: str
    kind: str  # mock | openai_compatible | cli
    default_base_url: str = ""
    default_model: str = ""
    needs_key: bool = False
    command: str = ""
    probe_url: str = ""  # GET this to detect local servers
    hint: str = ""


def _host() -> str:
    # inside docker, host services live at host.docker.internal
    return "host.docker.internal" if os.environ.get("DOCKERIZED") == "true" else "localhost"


PRESETS: list[Preset] = [
    Preset(id="mock", label="Built-in offline mode", kind="mock",
           hint="Deterministic, private, always available. Handles common logging phrasing."),
    Preset(id="openai", label="OpenAI", kind="openai_compatible",
           default_base_url="https://api.openai.com/v1", default_model="gpt-4o-mini",
           needs_key=True, hint="Hosted. Uses your API key, stored server-side only."),
    Preset(id="ollama", label="Ollama (local)", kind="openai_compatible",
           default_base_url=f"http://{_host()}:11434/v1", default_model="llama3.1",
           probe_url=f"http://{_host()}:11434/api/tags",
           hint="Fully local and free. Install ollama and pull a model, e.g. llama3.1."),
    Preset(id="lmstudio", label="LM Studio (local)", kind="openai_compatible",
           default_base_url=f"http://{_host()}:1234/v1", default_model="local-model",
           probe_url=f"http://{_host()}:1234/v1/models",
           hint="Fully local. Start the LM Studio local server first."),
    Preset(id="openai_compatible", label="Custom OpenAI-compatible", kind="openai_compatible",
           default_base_url="", default_model="", needs_key=False,
           hint="Any /v1/chat/completions endpoint (vLLM, LiteLLM, Together, Groq…)."),
    Preset(id="claude_code", label="Claude Code (CLI)", kind="cli", command="claude",
           hint="Uses your local Claude Code login. No API key needed; runs on this machine."),
    Preset(id="codex_cli", label="Codex CLI", kind="cli", command="codex",
           hint="Uses your local Codex login. Runs non-interactively (codex exec)."),
    Preset(id="opencode", label="opencode (CLI)", kind="cli", command="opencode",
           hint="Uses your local opencode setup and configured model."),
]

PRESET_BY_ID = {p.id: p for p in PRESETS}

# AI privacy modes (spec §92)
AI_MODES = ("local-only", "hybrid", "hosted")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _is_local_url(url: str) -> bool:
    from urllib.parse import urlparse
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    return host in LOCAL_HOSTS or host.endswith((".local", ".internal"))

_detect_cache: dict[str, tuple[float, bool]] = {}
_DETECT_TTL = 30.0


async def _probe(url: str) -> bool:
    cached = _detect_cache.get(url)
    now = time.monotonic()
    if cached and now - cached[0] < _DETECT_TTL:
        return cached[1]
    ok = False
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            ok = (await client.get(url)).status_code < 500
    except Exception:
        ok = False
    _detect_cache[url] = (now, ok)
    return ok


async def detect_providers() -> list[dict[str, Any]]:
    out = []
    for p in PRESETS:
        detected = True
        if p.kind == "cli":
            detected = shutil.which(p.command) is not None
        elif p.probe_url:
            detected = await _probe(p.probe_url)
        out.append({
            "id": p.id, "label": p.label, "kind": p.kind, "detected": detected,
            "needs_key": p.needs_key, "default_base_url": p.default_base_url,
            "default_model": p.default_model, "hint": p.hint,
        })
    return out


# ---------------- per-user settings ----------------

def get_ai_pref(pref: UserPreference | None) -> dict:
    data = (pref.data if pref else {}) or {}
    return dict(data.get("ai") or {})


def mask_ai_pref(ai: dict) -> dict:
    out = {k: v for k, v in ai.items() if k != "api_key"}
    out["has_api_key"] = bool(ai.get("api_key"))
    return out


def resolve_provider_from_pref(ai: dict) -> AIProvider:
    settings = get_settings()
    mode = ai.get("mode", "hybrid")
    preset = PRESET_BY_ID.get(ai.get("provider") or "")

    if mode == "local-only":
        # enforce: only the offline provider or local HTTP endpoints ever run.
        # CLIs are excluded — Claude Code/Codex/opencode call their own hosted
        # backends under the hood, so they are not local-only safe.
        if preset and preset.kind == "openai_compatible":
            base_url = ai.get("base_url") or preset.default_base_url
            if base_url and _is_local_url(base_url):
                return OpenAICompatibleProvider(
                    base_url=base_url,
                    api_key=ai.get("api_key") or "",
                    model=ai.get("model") or preset.default_model or settings.ai_model,
                )
        return MockProvider()

    if preset is None or preset.id == "mock":
        # env-level override still wins over an unset user pref
        if not ai.get("provider") and settings.ai_provider == "openai_compatible":
            return OpenAICompatibleProvider()
        return MockProvider()
    if preset.kind == "cli":
        return CliProvider(preset.command, model=ai.get("model") or None)
    base_url = ai.get("base_url") or preset.default_base_url or settings.ai_base_url
    api_key = ai.get("api_key") or (settings.ai_api_key if preset.id == "openai" else "")
    model = ai.get("model") or preset.default_model or settings.ai_model
    return OpenAICompatibleProvider(base_url=base_url, api_key=api_key, model=model)


async def provider_for_user(db: AsyncSession, user: User) -> AIProvider:
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    return resolve_provider_from_pref(get_ai_pref(pref))


async def save_ai_pref(db: AsyncSession, user: User, ai: dict) -> dict:
    pref = (await db.execute(select(UserPreference).where(UserPreference.user_id == user.id))).scalar_one_or_none()
    if pref is None:
        pref = UserPreference(user_id=user.id, data={})
        db.add(pref)
        await db.flush()
    existing = get_ai_pref(pref)
    # empty api_key field = keep the stored one
    if "api_key" in ai and not ai["api_key"]:
        ai = {k: v for k, v in ai.items() if k != "api_key"}
    merged = {**existing, **ai}
    pref.data = {**(pref.data or {}), "ai": merged}
    await db.commit()
    return mask_ai_pref(merged)
