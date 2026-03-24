"""Pydantic schemas for the transcription pipeline."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

import numpy as np
from pydantic import BaseModel, Field


class AudioSegment(BaseModel):
    """A chunk of audio data ready for transcription."""

    audio: list[float] = Field(description="PCM samples (16kHz mono float32)")
    sample_rate: int = 16000
    timestamp_start: float = Field(description="Seconds since session start")
    timestamp_end: float = Field(description="Seconds since session start")
    source: str = "microphone"

    class Config:
        arbitrary_types_allowed = True

    def to_numpy(self) -> np.ndarray:
        return np.array(self.audio, dtype=np.float32)


class TranscriptionResult(BaseModel):
    """Raw output from Whisper."""

    text: str
    language: str = "ja"
    confidence: float = 0.0
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0


class SpeakerMatch(BaseModel):
    """Result of speaker identification."""

    speaker_id: str = "unknown"
    speaker_name: str = "Unknown"
    confidence: float = 0.0


class TranscriptEntry(BaseModel):
    """A single finalized transcript entry with speaker info."""

    id: str = Field(default_factory=lambda: "")
    text: str
    raw_text: str = ""
    speaker_name: str = "Unknown"
    speaker_id: str = "unknown"
    speaker_confidence: float = 0.0
    cluster_id: str | None = None
    suggested_speaker_id: str | None = None
    suggested_speaker_name: str | None = None
    source: str = ""
    timestamp_start: float = 0.0
    timestamp_end: float = 0.0
    created_at: datetime = Field(default_factory=datetime.now)
    bookmarked: bool = False
    refined: bool = False


class SessionStatus(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"


class SessionInfo(BaseModel):
    """Current session state exposed via API."""

    status: SessionStatus = SessionStatus.IDLE
    session_id: str = ""
    started_at: datetime | None = None
    segment_count: int = 0
    entry_count: int = 0
    elapsed_seconds: float = 0.0
