import { useEffect, useState } from "react";
import { getGpuStatus, getHealth, getAudioDevices } from "../lib/apiHealth";
import { getModelStatus, switchModel, warmModelCache, getModelLoadingStatus } from "../lib/apiSession";
import { getGeminiModels, setGeminiModel } from "../lib/apiSummary";
import { getConfigStatus, setTextRefine } from "../lib/apiConfig";
import type { GpuStatus, AudioDevice, ModelStatus, GeminiModelInfo } from "../lib/types";
import SettingsApiKey from "./settings/SettingsApiKey";
import SettingsWhisperModel from "./settings/SettingsWhisperModel";
import SettingsGeminiModel from "./settings/SettingsGeminiModel";
import SettingsGpu from "./settings/SettingsGpu";
import SettingsAudio from "./settings/SettingsAudio";
import SettingsScreenCapture from "./settings/SettingsScreenCapture";
import SettingsMeeting from "./settings/SettingsMeeting";

export default function Settings() {
  const [health, setHealth] = useState("");
  const [gpu, setGpu] = useState<GpuStatus | null>(null);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [switching, setSwitching] = useState(false);
  const [switchStage, setSwitchStage] = useState("");
  const [switchProgress, setSwitchProgress] = useState(0);
  const [cacheWarming, setCacheWarming] = useState(false);
  const [error, setError] = useState("");
  const [geminiModels, setGeminiModels] = useState<GeminiModelInfo[]>([]);
  const [geminiCurrent, setGeminiCurrent] = useState("");
  const [selectedGemini, setSelectedGemini] = useState("");
  const [switchingGemini, setSwitchingGemini] = useState(false);
  const [apiKeySet, setApiKeySet] = useState(false);
  const [apiKeyMasked, setApiKeyMasked] = useState<string | null>(null);
  const [textRefineEnabled, setTextRefineEnabled] = useState(false);

  const refresh = async () => {
    try {
      const [h, g, d, m, gm, cfg] = await Promise.all([
        getHealth(),
        getGpuStatus(),
        getAudioDevices(),
        getModelStatus(),
        getGeminiModels(),
        getConfigStatus(),
      ]);
      setHealth(h.status);
      setGpu(g);
      setDevices(d.devices);
      setModel(m);
      setSelectedModel(m.current_model);
      setGeminiModels(gm.models);
      setGeminiCurrent(gm.current_model);
      setSelectedGemini(gm.current_model);
      setApiKeySet(cfg.gemini_api_key_set);
      setApiKeyMasked(cfg.gemini_api_key_masked);
      setTextRefineEnabled(cfg.text_refine_enabled ?? false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleSelectedModelChange = (value: string) => {
    setSelectedModel(value);
    // Start background cache warming when user selects a different model
    if (value !== model?.current_model) {
      setCacheWarming(true);
      warmModelCache(value).catch(() => {}).finally(() => setCacheWarming(false));
    }
  };

  const handleSwitch = async () => {
    if (!selectedModel || selectedModel === model?.current_model) return;
    setSwitching(true);
    setSwitchStage("warming");
    setSwitchProgress(0.1);
    setError("");

    // Poll loading status while switching
    const pollInterval = setInterval(async () => {
      try {
        const status = await getModelLoadingStatus();
        setSwitchStage(status.stage);
        setSwitchProgress(status.progress);
      } catch {
        // ignore poll errors
      }
    }, 500);

    try {
      await switchModel({ model_size: selectedModel });
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      clearInterval(pollInterval);
      setSwitching(false);
      setSwitchStage("");
      setSwitchProgress(0);
    }
  };

  const handleGeminiSwitch = async () => {
    if (!selectedGemini || selectedGemini === geminiCurrent) return;
    setSwitchingGemini(true);
    setError("");
    try {
      await setGeminiModel(selectedGemini);
      setGeminiCurrent(selectedGemini);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSwitchingGemini(false);
    }
  };

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <h2 className="text-lg font-semibold">設定</h2>

      {error && (
        <div className="p-3 bg-red-900/50 border border-red-700 rounded text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-300 ml-2 shrink-0">&#x2715;</button>
        </div>
      )}

      {/* Health */}
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-slate-300">ヘルスチェック</h3>
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full ${health === "ok" ? "bg-emerald-400" : "bg-red-400"}`} />
          <span className="text-sm">{health || "確認中..."}</span>
          <button onClick={refresh} className="text-xs text-slate-400 hover:text-slate-200 ml-2">
            更新
          </button>
        </div>
      </section>

      <SettingsApiKey
        apiKeySet={apiKeySet}
        apiKeyMasked={apiKeyMasked}
        onSaved={refresh}
      />

      <SettingsWhisperModel
        model={model}
        selectedModel={selectedModel}
        switching={switching}
        switchStage={switchStage}
        switchProgress={switchProgress}
        cacheWarming={cacheWarming}
        onSelectedModelChange={handleSelectedModelChange}
        onSwitch={handleSwitch}
      />

      <SettingsGeminiModel
        geminiModels={geminiModels}
        geminiCurrent={geminiCurrent}
        selectedGemini={selectedGemini}
        switchingGemini={switchingGemini}
        onSelectedGeminiChange={setSelectedGemini}
        onSwitch={handleGeminiSwitch}
      />

      <SettingsGpu gpu={gpu} />

      <SettingsAudio devices={devices} />

      <SettingsMeeting />

      <SettingsScreenCapture />

      {/* テキスト補正 */}
      <section className="space-y-2">
        <h3 className="text-sm font-medium text-slate-300">テキスト補正（AI）</h3>
        <p className="text-xs text-slate-500">Gemini AIで漢字変換と専門用語を自動補正します（要ネットワーク接続）</p>
        <label className="flex items-center gap-2 text-sm cursor-pointer">
          <input
            type="checkbox"
            checked={textRefineEnabled}
            disabled={!apiKeySet}
            onChange={async (e) => {
              const enabled = e.target.checked;
              setTextRefineEnabled(enabled);
              try {
                await setTextRefine(enabled);
              } catch {
                setTextRefineEnabled(!enabled);
              }
            }}
            className="rounded"
          />
          テキスト補正を有効にする
        </label>
        {!apiKeySet && (
          <p className="text-xs text-amber-400">Gemini APIキーが設定されていません</p>
        )}
      </section>
    </div>
  );
}
