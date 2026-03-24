import type { AudioDevice } from "../../lib/types";

interface Props {
  devices: AudioDevice[];
}

export default function SettingsAudio({ devices }: Props) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">オーディオデバイス</h3>
      <div className="space-y-1">
        {devices.map((d) => (
          <div key={d.index} className="flex items-center gap-2 text-sm py-1">
            <span
              className={`px-1.5 py-0.5 rounded text-xs ${
                d.is_loopback
                  ? "bg-violet-800 text-violet-200"
                  : "bg-emerald-800 text-emerald-200"
              }`}
            >
              {d.is_loopback ? "loopback" : "input"}
            </span>
            <span className="text-slate-300">{d.name}</span>
            <span className="text-slate-500 text-xs">
              {d.default_sample_rate}Hz {d.max_input_channels}ch
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
