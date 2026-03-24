import type { GpuStatus } from "../../lib/types";

interface Props {
  gpu: GpuStatus | null;
}

export default function SettingsGpu({ gpu }: Props) {
  if (!gpu) return null;

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">GPU</h3>
      {gpu.available ? (
        <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <span className="text-slate-400">デバイス</span>
          <span>{gpu.name}</span>
          <span className="text-slate-400">温度</span>
          <span>{gpu.temperature_c}°C</span>
          <span className="text-slate-400">使用率</span>
          <span>{gpu.gpu_utilization_pct}%</span>
          <span className="text-slate-400">VRAM</span>
          <span>
            {gpu.vram_used_mb} / {gpu.vram_total_mb} MB ({gpu.vram_free_mb} MB 空き)
          </span>
        </div>
      ) : (
        <p className="text-sm text-slate-400">GPU が利用できません</p>
      )}
    </section>
  );
}
