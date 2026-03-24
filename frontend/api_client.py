"""HTTP client for the backend API."""

from __future__ import annotations

import httpx

BASE_URL = "http://127.0.0.1:8000"


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


# --- Health ---

def health() -> dict:
    return httpx.get(_url("/api/health"), timeout=5).json()


def gpu_status() -> dict:
    return httpx.get(_url("/api/health/gpu"), timeout=5).json()


# --- Audio ---

def audio_devices() -> dict:
    return httpx.get(_url("/api/audio/devices"), timeout=5).json()


# --- Session ---

def session_start(device_index: int | None = None,
                  loopback_device_index: int | None = None,
                  session_name: str = "") -> dict:
    body: dict = {}
    if device_index is not None:
        body["device_index"] = device_index
    if loopback_device_index is not None:
        body["loopback_device_index"] = loopback_device_index
    if session_name:
        body["session_name"] = session_name
    return httpx.post(_url("/api/session/start"), json=body, timeout=120).json()


def session_stop() -> dict:
    return httpx.post(_url("/api/session/stop"), timeout=30).json()


def session_pause() -> dict:
    return httpx.post(_url("/api/session/pause"), timeout=10).json()


def session_status() -> dict:
    return httpx.get(_url("/api/session/status"), timeout=5).json()


def register_speaker_from_entry(entry_index: int, name: str) -> dict:
    r = httpx.post(_url("/api/session/register-speaker"),
                   json={"entry_index": entry_index, "name": name}, timeout=10)
    r.raise_for_status()
    return r.json()


def get_session_entries() -> list[dict]:
    return httpx.get(_url("/api/session/entries"), timeout=5).json().get("entries", [])


# --- Model ---

def get_model() -> dict:
    return httpx.get(_url("/api/session/model"), timeout=5).json()


def switch_model(model_size: str) -> dict:
    return httpx.post(_url("/api/session/model"),
                      json={"model_size": model_size}, timeout=120).json()


# --- Speakers ---

def list_speakers() -> list[dict]:
    return httpx.get(_url("/api/speakers"), timeout=5).json().get("speakers", [])


def register_speaker(name: str, audio_files: list) -> dict:
    files = [("files", (f"sample_{i}.wav", f, "audio/wav")) for i, f in enumerate(audio_files)]
    return httpx.post(_url("/api/speakers"), data={"name": name}, files=files, timeout=120).json()


def delete_speaker(speaker_id: str) -> dict:
    return httpx.delete(_url(f"/api/speakers/{speaker_id}"), timeout=10).json()


# --- Dictionary ---

def get_dictionary() -> dict:
    return httpx.get(_url("/api/dictionary"), timeout=5).json()


def reload_dictionary() -> dict:
    return httpx.post(_url("/api/dictionary/reload"), timeout=5).json()


def add_replacement(from_text: str, to_text: str,
                    is_regex: bool = False, note: str = "") -> dict:
    return httpx.post(_url("/api/dictionary"), json={
        "from_text": from_text, "to_text": to_text,
        "is_regex": is_regex, "note": note,
    }, timeout=5).json()


def delete_replacement(index: int) -> dict:
    return httpx.delete(_url(f"/api/dictionary/{index}"), timeout=5).json()


def update_fillers(fillers: list[str] | None = None, enabled: bool | None = None) -> dict:
    body = {}
    if fillers is not None:
        body["fillers"] = fillers
    if enabled is not None:
        body["filler_removal_enabled"] = enabled
    return httpx.put(_url("/api/dictionary/fillers"), json=body, timeout=5).json()


def test_dictionary(text: str) -> dict:
    return httpx.post(_url("/api/dictionary/test"), json={"text": text}, timeout=5).json()


# --- Transcripts ---

def list_sessions() -> list[dict]:
    return httpx.get(_url("/api/transcripts"), timeout=5).json().get("sessions", [])


def get_transcript(session_id: str) -> dict:
    return httpx.get(_url(f"/api/transcripts/{session_id}"), timeout=10).json()


def export_transcript(session_id: str, fmt: str = "txt") -> str:
    r = httpx.get(_url(f"/api/transcripts/{session_id}/export?format={fmt}"), timeout=10)
    return r.text


def delete_session(session_id: str) -> dict:
    return httpx.delete(_url(f"/api/transcripts/{session_id}"), timeout=10).json()


# --- Summary ---

def generate_summary(session_id: str) -> dict:
    return httpx.post(_url("/api/summary/generate"),
                      json={"session_id": session_id}, timeout=120).json()


def get_summary(session_id: str) -> dict:
    return httpx.get(_url(f"/api/summary/{session_id}"), timeout=10).json()


# --- Call Detection ---

def call_detection_pending() -> dict:
    return httpx.get(_url("/api/call-detection/pending"), timeout=3).json()


def call_detection_dismiss(window_title: str) -> dict:
    return httpx.post(_url("/api/call-detection/dismiss"),
                      params={"window_title": window_title}, timeout=3).json()


def call_detection_config(enabled: bool | None = None) -> dict:
    if enabled is not None:
        return httpx.post(_url("/api/call-detection/config"),
                          json={"enabled": enabled}, timeout=3).json()
    return httpx.get(_url("/api/call-detection/config"), timeout=3).json()
