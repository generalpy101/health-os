"""Provider presets, availability detection, and per-user provider resolution.

Provider kinds:
  mock               built-in offline rule-based provider (always available)
  openai_compatible  OpenAI / Ollama / LM Studio / vLLM / any compatible endpoint
  cli                local agent CLIs (Claude Code, Codex, opencode) run non-interactively

Users pick provider + model + base_url + key in Settings (stored server-side in
user_preferences; keys are never returned to the browser).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
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


# curated fallbacks for CLIs that don't expose a list command
# (aliases first — they always resolve to the provider's latest; full IDs after)
CLI_MODEL_SUGGESTIONS = {
    "claude": ["sonnet", "opus", "haiku",
               "claude-sonnet-4-5", "claude-opus-4-5", "claude-opus-4-6", "claude-opus-4-7",
               "claude-haiku-4-5", "claude-fable-5", "claude-mythos-5"],
    "codex": ["gpt-5", "gpt-5-codex", "gpt-5.1", "codex-mini-latest", "o4-mini"],
}

_models_cache: dict[str, tuple[float, list[str]]] = {}
_MODELS_TTL = 60.0


async def _cli_models_claude() -> list[str] | None:
    """Live alias discovery via `claude -p /model` (prints 'Available: ...')."""
    if not shutil.which("claude"):
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", "/model", stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, cwd=tempfile.gettempdir(),
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        text = out.decode(errors="replace")
        m = re.search(r"Available:\s*(.+?)(?:\.|$)", text, re.S)
        if not m:
            return None
        aliases = [a.strip() for a in m.group(1).split(",")]
        # drop meta-entries; keep aliases (full IDs remain free-text)
        return [a for a in aliases if a and "model ID" not in a and a != "default"]
    except Exception:
        return None


async def discover_models(preset_id: str, base_url: str = "", api_key: str = "") -> dict:
    """Best-effort model discovery for a provider. Always returns a list;
    `detected` tells the UI whether a live source was found."""
    preset = PRESET_BY_ID.get(preset_id)
    if preset is None or preset.id == "mock":
        return {"models": ["mock"], "detected": True, "source": "static", "default": "mock"}

    cache_key = f"{preset_id}|{base_url}"
    cached = _models_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _MODELS_TTL:
        return {"models": cached[1], "detected": True, "source": "cache",
                "default": preset.default_model or cached[1][0]}

    models: list[str] = []
    detected = False

    if preset.kind == "cli":
        if preset.command == "opencode" and shutil.which("opencode"):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "opencode", "models", stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL, cwd=tempfile.gettempdir(),
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
                models = [l.strip() for l in out.decode().splitlines() if "/" in l]
                detected = bool(models)
            except Exception:
                detected = False
        elif preset.command == "claude":
            live = await _cli_models_claude()
            if live:
                models = live
                detected = True
            else:
                models = list(CLI_MODEL_SUGGESTIONS["claude"])
                detected = shutil.which("claude") is not None
        else:
            detected = shutil.which(preset.command) is not None
            models = list(CLI_MODEL_SUGGESTIONS.get(preset.command, []))
        return {"models": models, "detected": detected, "source": "cli",
                "default": "CLI default" if preset.command in ("claude", "codex", "opencode") else models[0] if models else ""}

    # openai_compatible kinds: GET {base}/models (OpenAI-style), fallback to
    # Ollama native {host}/api/tags
    base = (base_url or preset.default_base_url or "").rstrip("/")
    if not base:
        return {"models": [], "detected": False, "source": "none", "default": preset.default_model}
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base}/models", headers=headers)
            if r.status_code < 400:
                data = r.json()
                models = sorted(m.get("id", "") for m in data.get("data", []) if m.get("id"))
                detected = True
    except Exception:
        pass
    if not models and base.endswith("/v1"):
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{base[:-3]}/api/tags")
                if r.status_code < 400:
                    models = sorted(m.get("name", "") for m in r.json().get("models", []) if m.get("name"))
                    detected = True
        except Exception:
            pass

    if models:
        _models_cache[cache_key] = (time.monotonic(), models)
    return {"models": models, "detected": detected, "source": "live", "default": preset.default_model}


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
