from fastapi import APIRouter

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def health_check():
    return {"status": "ok"}


@router.get("/gpu")
async def gpu_status():
    try:
        from pynvml import (
            nvmlDeviceGetHandleByIndex,
            nvmlDeviceGetMemoryInfo,
            nvmlDeviceGetName,
            nvmlDeviceGetTemperature,
            nvmlDeviceGetUtilizationRates,
            nvmlInit,
            nvmlShutdown,
            NVML_TEMPERATURE_GPU,
        )

        nvmlInit()
        try:
            handle = nvmlDeviceGetHandleByIndex(0)

            name = nvmlDeviceGetName(handle)
            mem_info = nvmlDeviceGetMemoryInfo(handle)
            temp = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
            util = nvmlDeviceGetUtilizationRates(handle)
        finally:
            nvmlShutdown()

        return {
            "available": True,
            "name": name,
            "temperature_c": temp,
            "gpu_utilization_pct": util.gpu,
            "vram_total_mb": mem_info.total // (1024 * 1024),
            "vram_used_mb": mem_info.used // (1024 * 1024),
            "vram_free_mb": mem_info.free // (1024 * 1024),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}
