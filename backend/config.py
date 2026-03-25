import os
import sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _base_dir() -> Path:
    """Get project base directory (handles PyInstaller bundle)."""
    if getattr(sys, "frozen", False):
        # PyInstaller exe is in sidecar/ subdir, base is one level up
        return Path(sys.executable).parent.parent
    return Path(__file__).resolve().parent.parent


def _default_data_dir() -> Path:
    """Get default data directory: %APPDATA%/transcriber or base_dir/data."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "transcriber"
    return _base_dir() / "data"


def _env_file_path() -> Path:
    """Get .env file path: %APPDATA%/transcriber/.env (survives redeployment)."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "transcriber" / ".env"
    return _base_dir() / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file_path()),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    gemini_api_key: str = ""
    hf_token: str = ""

    # Gemini
    gemini_model: str = "gemini-3-flash-preview"

    # Whisper
    whisper_model: str = "kotoba-v2.0"
    whisper_language: str = "ja"

    # Audio
    audio_sample_rate: int = 16000
    audio_channels: int = 1

    # VAD
    vad_threshold: float = 0.5
    vad_min_silence_ms: int = 500
    vad_max_segment_s: float = 10.0
    vad_min_segment_s: float = 0.5

    # Speaker identification (WeSpeaker ResNet34-LM: EER 0.723%)
    speaker_similarity_threshold: float = 0.65
    speaker_suggestion_threshold: float = 0.45  # Suggest registered speaker if score >= this but < similarity_threshold
    speaker_cluster_threshold: float = 0.60
    speaker_cluster_merge_threshold: float = 0.65
    speaker_max_count: int = 7

    # Small cluster merge (Phase 2.5)
    speaker_small_cluster_count: int = 3
    speaker_small_cluster_merge_threshold: float = 0.50

    # Speaker profile continuous learning
    speaker_max_samples: int = 30
    speaker_sample_rotation_enabled: bool = True
    speaker_embedding_momentum: float = 0.9
    speaker_min_session_matches: int = 3
    speaker_sample_min_quality: float = 0.3

    # Eigengap speaker count estimation
    eigengap_enabled: bool = True
    eigengap_min_segments: int = 15
    eigengap_update_interval: int = 10

    # Backend
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    # Deployment mode: "standalone" (local audio), "server" (remote audio via WebSocket)
    deployment_mode: str = "standalone"
    auth_token: str = ""  # Bearer token for server mode (empty = no auth)
    max_concurrent_sessions: int = 5

    # Frontend
    frontend_port: int = 7860

    # Paths
    data_dir: Path = _default_data_dir()
    dictionary_shared_path: str = ""

    @property
    def speakers_dir(self) -> Path:
        return self.data_dir / "speakers"

    @property
    def sessions_dir(self) -> Path:
        override = os.environ.get("SESSIONS_DIR")
        if override:
            return Path(override)
        return self.data_dir / "sessions"

    @property
    def dictionary_path(self) -> Path:
        if self.dictionary_shared_path:
            shared = Path(self.dictionary_shared_path)
            if shared.exists():
                return shared
        return self.data_dir / "dictionary.json"

    # Hallucination filtering
    hallucination_rms_threshold: float = 0.003
    hallucination_no_speech_threshold: float = 0.7
    hallucination_logprob_threshold: float = -1.2
    hallucination_compression_threshold: float = 2.4
    hallucination_phrase_max_duration: float = 3.0
    hallucination_speech_ratio_threshold: float = 0.7
    hallucination_logprob_rescue_threshold: float = -0.7

    # Debug
    debug_save_segments: bool = True

    # GPU
    gpu_temp_warning: int = 78
    gpu_temp_critical: int = 80

    # Segmentation refinement (Pass 2)
    segmentation_refine_enabled: bool = True
    segmentation_refine_interval_s: float = 10.0
    segmentation_refine_window_s: float = 30.0

    # Screenshots
    screenshot_enabled: bool = True
    screenshot_interval: int = 10
    screenshot_quality: int = 80

    # Call auto-detection
    call_detection_enabled: bool = True
    call_detection_interval: float = 5.0
    call_detection_dismiss_duration: float = 300.0
    call_notification_enabled: bool = True  # Windows toast notification for detected calls

    # Text refinement (Pass 2 — Gemini Flash)
    text_refine_enabled: bool = True
    text_refine_batch_size: int = 5
    text_refine_delay_s: float = 3.0
    text_refine_model: str = "gemini-2.5-flash"

    # Audio saving (transcription continues regardless)
    audio_saving_enabled: bool = True


settings = Settings()
