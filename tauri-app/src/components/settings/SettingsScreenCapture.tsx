import { useEffect, useState } from "react";
import { getScreenCaptureConfig, setScreenCaptureConfig } from "../../lib/apiScreenshots";

const INTERVAL_OPTIONS = [
  { value: 5, label: "5秒" },
  { value: 10, label: "10秒" },
  { value: 30, label: "30秒" },
  { value: 60, label: "60秒" },
];

export default function SettingsScreenCapture() {
  const [enabled, setEnabled] = useState(true);
  const [interval, setIntervalValue] = useState(10);
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getScreenCaptureConfig()
      .then((data) => {
        setEnabled(data.screenshot_enabled);
        setIntervalValue(data.screenshot_interval);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const handleToggle = async () => {
    setSaving(true);
    try {
      const result = await setScreenCaptureConfig({ screenshot_enabled: !enabled });
      setEnabled(result.screenshot_enabled);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  };

  const handleIntervalChange = async (value: number) => {
    setSaving(true);
    try {
      const result = await setScreenCaptureConfig({ screenshot_interval: value });
      setIntervalValue(result.screenshot_interval);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) return null;

  return (
    <section className="space-y-2">
      <h3 className="text-sm font-medium text-slate-300">スクリーンキャプチャ</h3>

      <div className="flex items-center gap-3">
        <button
          onClick={handleToggle}
          disabled={saving}
          className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
            enabled ? "bg-cyan-600" : "bg-slate-600"
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              enabled ? "translate-x-[18px]" : "translate-x-[2px]"
            }`}
          />
        </button>
        <span className="text-sm text-slate-300">
          {enabled ? "有効" : "無効"}
        </span>
      </div>

      {enabled && (
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-400">キャプチャ間隔:</span>
          <select
            value={interval}
            onChange={(e) => handleIntervalChange(Number(e.target.value))}
            disabled={saving}
            className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm"
          >
            {INTERVAL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      )}
    </section>
  );
}
