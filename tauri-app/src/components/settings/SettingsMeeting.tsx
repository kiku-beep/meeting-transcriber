import { useEffect, useState } from "react";
import { getMeetingConfig, setMeetingConfig } from "../../lib/apiConfig";

interface ToggleItem {
  key: "call_notification_enabled" | "audio_saving_enabled";
  label: string;
  description: string;
}

const TOGGLES: ToggleItem[] = [
  {
    key: "call_notification_enabled",
    label: "ポップアップ通知",
    description: "通話検出時にWindows通知を表示",
  },
  {
    key: "audio_saving_enabled",
    label: "音声ファイル保存",
    description: "録音音声をWAVファイルとして保存",
  },
];

export default function SettingsMeeting() {
  const [config, setConfig] = useState({
    call_notification_enabled: true,
    screenshot_enabled: true,
    audio_saving_enabled: true,
  });
  const [saving, setSaving] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getMeetingConfig()
      .then((data) => {
        setConfig(data);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, []);

  const handleToggle = async (key: ToggleItem["key"]) => {
    setSaving(true);
    try {
      const result = await setMeetingConfig({ [key]: !config[key] });
      setConfig(result);
    } catch {
      // silently fail
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) return null;

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">会議設定</h3>

      {TOGGLES.map((item) => (
        <div key={item.key} className="flex items-center gap-3">
          <button
            onClick={() => handleToggle(item.key)}
            disabled={saving}
            className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
              config[item.key] ? "bg-cyan-600" : "bg-slate-600"
            }`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                config[item.key] ? "translate-x-[18px]" : "translate-x-[2px]"
              }`}
            />
          </button>
          <div className="min-w-0">
            <span className="text-sm text-slate-300">{item.label}</span>
            <span className="text-xs text-slate-500 ml-2">{item.description}</span>
          </div>
        </div>
      ))}
    </section>
  );
}
