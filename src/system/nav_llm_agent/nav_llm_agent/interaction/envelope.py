from __future__ import annotations

import json
import time
import uuid


SCHEMA = "luka.interaction.text.v1"
ALLOWED_SOURCES = {
    "voice_local",
    "voice_drobotics",
    "xiaozhi_protocol",
    "app",
    "dashboard",
    "legacy_voice",
}


def normalize_envelope(raw: str, default_source: str = "legacy_voice") -> dict:
    raw = str(raw or "").strip()
    if not raw:
        raise ValueError("empty interaction input")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {"text": raw, "source": default_source}
    if not isinstance(value, dict):
        raise ValueError("interaction input must be text or a JSON object")

    text = str(value.get("text") or "").strip()
    if not 1 <= len(text) <= 1000:
        raise ValueError("interaction text must contain 1..1000 characters")
    source = str(value.get("source") or default_source).strip().lower()
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"unsupported interaction source: {source}")

    captured_at = value.get("captured_at")
    if not isinstance(captured_at, (int, float)):
        captured_at = time.time()

    session_id = str(value.get("session_id") or "").strip()
    turn_id = str(value.get("turn_id") or "").strip()
    provided_turn_id = bool(turn_id)
    if not turn_id:
        turn_id = uuid.uuid4().hex

    result = {
        "schema": SCHEMA,
        "text": text,
        "source": source,
        "session_id": session_id,
        "turn_id": turn_id,
        "captured_at": float(captured_at),
        "_provided_turn_id": provided_turn_id,
    }
    if isinstance(value.get("speaker"), dict):
        result["speaker"] = value["speaker"]
    metadata = value.get("metadata")
    if isinstance(metadata, dict):
        result["metadata"] = metadata
    return result


def dedup_key(env: dict) -> str:
    if env.get("_provided_turn_id"):
        return f"{env['source']}:{env.get('session_id','')}:{env['turn_id']}"
    return f"{env['source']}:{env.get('session_id','')}:{env['text']}"


def public_envelope(env: dict) -> dict:
    result = dict(env)
    result.pop("_provided_turn_id", None)
    return result
