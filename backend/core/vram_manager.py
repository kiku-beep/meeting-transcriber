"""VRAM monitoring and model load management."""

from __future__ import annotations

import logging
import time as _time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VRAMStatus:
    total_mb: int
    used_mb: int
    free_mb: int
    temperature_c: int


_cache: VRAMStatus | None = None
_cache_time: float = 0


def get_vram_status() -> VRAMStatus | None:
    """Get current GPU VRAM and temperature status.

    Results are cached for 2 seconds to avoid excessive NVML calls.
    """
    global _cache, _cache_time
    now = _time.monotonic()
    if _cache and (now - _cache_time) < 2.0:
        return _cache

    try:
        import torch

        if not torch.cuda.is_available():
            return None

        mem_total = torch.cuda.get_device_properties(0).total_memory
        mem_reserved = torch.cuda.memory_reserved(0)
        mem_free = mem_total - mem_reserved

        # Temperature via nvidia_ml_py (separate from torch's pynvml)
        temp = _get_temperature()

        result = VRAMStatus(
            total_mb=mem_total // (1024 * 1024),
            used_mb=mem_reserved // (1024 * 1024),
            free_mb=mem_free // (1024 * 1024),
            temperature_c=temp,
        )
        _cache = result
        _cache_time = now
        return result
    except Exception:
        logger.warning("Failed to query GPU status", exc_info=True)
        return None


def _get_temperature() -> int:
    """Get GPU temperature, returns -1 on failure."""
    try:
        from pynvml import (
            nvmlDeviceGetHandleByIndex,
            nvmlDeviceGetTemperature,
            nvmlInit,
            nvmlShutdown,
            NVML_TEMPERATURE_GPU,
        )

        nvmlInit()
        try:
            handle = nvmlDeviceGetHandleByIndex(0)
            temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
        finally:
            nvmlShutdown()
        return temp
    except Exception:
        return -1


def check_vram_available(required_mb: int) -> bool:
    """Check if enough VRAM is available for a model load."""
    status = get_vram_status()
    if status is None:
        return True
    return status.free_mb >= required_mb


def check_temperature_safe(warning_c: int = 78) -> bool:
    """Check if GPU temperature is below warning threshold."""
    status = get_vram_status()
    if status is None:
        return True
    if status.temperature_c < 0:
        return True
    return status.temperature_c < warning_c
