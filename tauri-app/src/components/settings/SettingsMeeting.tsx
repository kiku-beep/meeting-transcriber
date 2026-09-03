import { useEffect, useState } from "react";
import {
  getMeetingConfig,
  getTopicTreeConfig,
  setMeetingConfig,
  setTopicTreeConfig,
  type TopicTreeConfig,
  type TopicTreeReasoningEffort,
} from "../../lib/apiConfig";

// 1回の更新に実測20〜35秒かかるため、下限は30秒（サーバ側でも弾く）。
const INTERVAL_OPTIONS = [60, 90, 120, 180, 300];

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
  const [topicConfig, setTopicConfig] = useState<TopicTreeConfig>({
    topic_tree_enabled: false,
    topic_tree_interval_s: 90,
    topic_tree_codex_reasoning_effort: "low",
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

    getTopicTreeConfig()
      .then(setTopicConfig)
      .catch(() => {
        // 既定値のまま表示する（古いbackendでも設定画面を壊さない）。
      });
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

  const handleTopicChange = async (patch: Partial<TopicTreeConfig>) => {
    setSaving(true);
    try {
      setTopicConfig(await setTopicTreeConfig(patch));
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

      <div className="flex items-center gap-3">
        <button
          onClick={() => handleTopicChange({ topic_tree_enabled: !topicConfig.topic_tree_enabled })}
          disabled={saving}
          className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${
            topicConfig.topic_tree_enabled ? "bg-cyan-600" : "bg-slate-600"
          }`}
        >
          <span
            className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
              topicConfig.topic_tree_enabled ? "translate-x-[18px]" : "translate-x-[2px]"
            }`}
          />
        </button>
        <div className="min-w-0">
          <span className="text-sm text-slate-300">論点ツリー</span>
          <span className="text-xs text-slate-500 ml-2">
            会議中に論点を自動抽出（次の録音から有効・AI利用枠を消費）
          </span>
        </div>
      </div>

      {topicConfig.topic_tree_enabled && (
        <div className="space-y-2 pl-12">
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500" htmlFor="topic-tree-interval">
              更新間隔
            </label>
            <select
              id="topic-tree-interval"
              value={topicConfig.topic_tree_interval_s}
              disabled={saving}
              onChange={(event) =>
                handleTopicChange({ topic_tree_interval_s: Number(event.target.value) })
              }
              className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300"
            >
              {INTERVAL_OPTIONS.map((seconds) => (
                <option key={seconds} value={seconds}>
                  {seconds}秒
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-3">
            <label className="text-xs text-slate-500" htmlFor="topic-tree-effort">
              推論レベル
            </label>
            <select
              id="topic-tree-effort"
              value={topicConfig.topic_tree_codex_reasoning_effort}
              disabled={saving}
              onChange={(event) =>
                handleTopicChange({
                  topic_tree_codex_reasoning_effort: event.target.value as TopicTreeReasoningEffort,
                })
              }
              className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-300"
            >
              <option value="low">low（最速・既定）</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="xhigh">xhigh</option>
              <option value="max">max（最高精度・最も遅い）</option>
            </select>
          </div>
          <p className="text-xs text-slate-500">
            高いほど精度は上がりますが1回の更新に時間がかかります。次の録音開始から反映されます。
          </p>
        </div>
      )}
    </section>
  );
}
