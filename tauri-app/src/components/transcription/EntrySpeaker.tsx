import { useState, useRef, useEffect } from "react";
import type { Speaker } from "../../lib/types";
import { getSavedSpeakerColor, saveSpeakerColor, getDefaultSpeakerColor, SPEAKER_COLOR_OPTIONS } from "../../lib/speakerColors";

function getSpeakerColor(speakerName: string, speakerId: string): string {
  if (speakerId === "unknown") return "text-slate-400";
  return getSavedSpeakerColor(speakerName) ?? getDefaultSpeakerColor(speakerName);
}

function getConfidenceDot(confidence: number): { color: string; label: string } {
  if (confidence >= 0.75) return { color: "bg-emerald-500", label: `信頼度: ${confidence.toFixed(2)}` };
  if (confidence >= 0.55) return { color: "bg-amber-500", label: `信頼度: ${confidence.toFixed(2)}` };
  if (confidence > 0) return { color: "bg-red-500", label: `信頼度: ${confidence.toFixed(2)}` };
  return { color: "bg-slate-600", label: "信頼度: なし" };
}

interface Props {
  speakerName: string;
  speakerId: string;
  speakerConfidence?: number;
  clusterId?: string | null;
  suggestedSpeakerId?: string | null;
  suggestedSpeakerName?: string | null;
  speakers?: Speaker[];
  onEditSpeaker?: (name: string, id: string) => Promise<void>;
  onEditSpeakerBulk?: (name: string, id: string) => Promise<void>;
  onNameCluster?: (clusterId: string, name: string, isGuest: boolean) => Promise<void>;
  onRegisterNewSpeaker?: (name: string, isGuest: boolean) => Promise<void>;
  onConfirmSuggestion?: (clusterId: string, speakerId: string, speakerName: string) => Promise<void>;
}

export default function EntrySpeaker({ speakerName, speakerId, speakerConfidence = 0, clusterId, suggestedSpeakerId, suggestedSpeakerName, speakers, onEditSpeaker, onEditSpeakerBulk, onNameCluster, onRegisterNewSpeaker, onConfirmSuggestion }: Props) {
  const [showSpeakerMenu, setShowSpeakerMenu] = useState(false);
  const [namingCluster, setNamingCluster] = useState(false);
  const [clusterName, setClusterName] = useState("");
  const [pendingSpeaker, setPendingSpeaker] = useState<{ name: string; id: string } | null>(null);
  const [registeringNew, setRegisteringNew] = useState(false);
  const [newSpeakerName, setNewSpeakerName] = useState("");
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [suggestionDismissed, setSuggestionDismissed] = useState(false);
  const [currentColor, setCurrentColor] = useState(() => getSpeakerColor(speakerName, speakerId));
  const speakerMenuRef = useRef<HTMLDivElement>(null);
  const clusterInputRef = useRef<HTMLInputElement>(null);
  const newSpeakerInputRef = useRef<HTMLInputElement>(null);

  // Update color when speakerName changes
  useEffect(() => {
    setCurrentColor(getSpeakerColor(speakerName, speakerId));
  }, [speakerName, speakerId]);

  // Close speaker menu / scope selection on outside click
  useEffect(() => {
    if (!showSpeakerMenu && !pendingSpeaker && !namingCluster) return;
    const handler = (e: MouseEvent) => {
      if (speakerMenuRef.current && !speakerMenuRef.current.contains(e.target as Node)) {
        setShowSpeakerMenu(false);
        setPendingSpeaker(null);
        setNamingCluster(false);
        setRegisteringNew(false);
        setShowColorPicker(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [showSpeakerMenu, pendingSpeaker, namingCluster]);

  // Focus cluster name input when entering naming mode
  useEffect(() => {
    if (namingCluster && clusterInputRef.current) {
      clusterInputRef.current.focus();
    }
  }, [namingCluster]);

  // Focus new speaker input when entering register mode
  useEffect(() => {
    if (registeringNew && newSpeakerInputRef.current) {
      newSpeakerInputRef.current.focus();
    }
  }, [registeringNew]);

  const handleSpeakerClick = () => {
    if (!onEditSpeaker || !speakers) return;
    setShowSpeakerMenu(true);
    setRegisteringNew(false);
    setShowColorPicker(false);
  };

  const handleSpeakerSelect = async (name: string, id: string) => {
    if (!onEditSpeaker) return;
    if (name === speakerName && id === speakerId) {
      setShowSpeakerMenu(false);
      return;
    }
    // If bulk callback exists, show scope selection
    if (onEditSpeakerBulk) {
      setShowSpeakerMenu(false);
      setPendingSpeaker({ name, id });
      return;
    }
    // No bulk option (e.g. History view) — single update directly
    setShowSpeakerMenu(false);
    await onEditSpeaker(name, id);
  };

  const handleScopeSelect = async (scope: "single" | "bulk") => {
    if (!pendingSpeaker) return;
    const { name, id } = pendingSpeaker;
    setPendingSpeaker(null);
    if (scope === "single" && onEditSpeaker) {
      await onEditSpeaker(name, id);
    } else if (scope === "bulk" && onEditSpeakerBulk) {
      await onEditSpeakerBulk(name, id);
    }
  };

  const handleStartNaming = () => {
    setShowSpeakerMenu(false);
    setClusterName("");
    setNamingCluster(true);
  };

  const handleNameClusterSubmit = async (isGuest: boolean = false) => {
    if (!onNameCluster || !clusterId || !clusterName.trim()) return;
    setNamingCluster(false);
    await onNameCluster(clusterId, clusterName.trim(), isGuest);
  };

  const handleClusterNameKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") {
      e.preventDefault();
      handleNameClusterSubmit(false);
    } else if (e.key === "Escape") {
      setNamingCluster(false);
    }
  };

  const handleRegisterNewSubmit = async (isGuest: boolean) => {
    if (!onRegisterNewSpeaker || !newSpeakerName.trim()) return;
    setShowSpeakerMenu(false);
    setRegisteringNew(false);
    await onRegisterNewSpeaker(newSpeakerName.trim(), isGuest);
  };

  const handleNewSpeakerKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter") {
      e.preventDefault();
      handleRegisterNewSubmit(false);
    } else if (e.key === "Escape") {
      setRegisteringNew(false);
    }
  };

  const handleColorSelect = (colorClass: string) => {
    saveSpeakerColor(speakerName, colorClass);
    setCurrentColor(colorClass);
    setShowColorPicker(false);
    setShowSpeakerMenu(false);
  };

  return (
    <span className="shrink-0 min-w-[5rem] relative" ref={speakerMenuRef}>
      <span className="inline-flex items-center gap-1">
        <span
          className={`font-medium ${currentColor} ${onEditSpeaker ? "cursor-pointer hover:underline" : ""}`}
          onClick={handleSpeakerClick}
          title={onEditSpeaker ? "クリックで話者変更" : undefined}
        >
          {speakerName}
        </span>
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full ${getConfidenceDot(speakerConfidence).color}`}
          title={getConfidenceDot(speakerConfidence).label}
        />
        {/* Speaker suggestion chip */}
        {suggestedSpeakerName && suggestedSpeakerId && clusterId && !suggestionDismissed && onConfirmSuggestion && (
          <span className="inline-flex items-center gap-0.5 ml-1">
            <button
              onClick={async () => {
                await onConfirmSuggestion(clusterId, suggestedSpeakerId, suggestedSpeakerName);
              }}
              className="text-xs px-1.5 py-0 rounded bg-cyan-800/60 hover:bg-cyan-700/80 text-cyan-300 border border-cyan-600/50"
              title={`${suggestedSpeakerName} として確定`}
            >
              → {suggestedSpeakerName}?
            </button>
            <button
              onClick={() => setSuggestionDismissed(true)}
              className="text-xs text-slate-500 hover:text-slate-300 px-0.5"
              title="却下"
            >
              ×
            </button>
          </span>
        )}
      </span>

      {/* Speaker dropdown */}
      {showSpeakerMenu && speakers && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-slate-700 border border-slate-600 rounded shadow-lg py-1 min-w-[8rem]">
          {speakers.map((s) => (
            <button
              key={s.id}
              onClick={() => handleSpeakerSelect(s.name, s.id)}
              className={`block w-full text-left px-3 py-1.5 text-sm hover:bg-slate-600 ${
                s.id === speakerId ? "text-cyan-400 font-medium" : "text-slate-200"
              }`}
            >
              {s.name}
            </button>
          ))}
          <button
            onClick={() => handleSpeakerSelect("Unknown", "unknown")}
            className={`block w-full text-left px-3 py-1.5 text-sm hover:bg-slate-600 ${
              speakerId === "unknown" ? "text-slate-400 font-medium" : "text-slate-400"
            }`}
          >
            Unknown
          </button>

          {/* New speaker registration */}
          {onRegisterNewSpeaker && (
            <>
              <div className="border-t border-slate-600 my-1" />
              {!registeringNew ? (
                <button
                  onClick={() => { setRegisteringNew(true); setNewSpeakerName(""); }}
                  className="block w-full text-left px-3 py-1.5 text-sm text-emerald-400 hover:bg-slate-600"
                >
                  新規登録...
                </button>
              ) : (
                <div className="px-2 py-1.5">
                  <input
                    ref={newSpeakerInputRef}
                    type="text"
                    value={newSpeakerName}
                    onChange={(e) => setNewSpeakerName(e.target.value)}
                    onKeyDown={handleNewSpeakerKeyDown}
                    placeholder="新しい話者名"
                    className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-xs text-slate-200 focus:outline-none focus:border-emerald-400"
                  />
                  <div className="flex gap-1.5 mt-1">
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => handleRegisterNewSubmit(false)}
                      disabled={!newSpeakerName.trim()}
                      className="flex-1 px-2 py-0.5 text-xs bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-600 disabled:text-slate-400 rounded text-white"
                    >
                      登録
                    </button>
                    <button
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => handleRegisterNewSubmit(true)}
                      disabled={!newSpeakerName.trim()}
                      className="flex-1 px-2 py-0.5 text-xs bg-amber-600 hover:bg-amber-700 disabled:bg-slate-600 disabled:text-slate-400 rounded text-white"
                    >
                      ゲスト
                    </button>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Color picker */}
          {speakerId !== "unknown" && (
            <>
              <div className="border-t border-slate-600 my-1" />
              {!showColorPicker ? (
                <button
                  onClick={() => setShowColorPicker(true)}
                  className="block w-full text-left px-3 py-1.5 text-sm text-slate-300 hover:bg-slate-600"
                >
                  色を変更...
                </button>
              ) : (
                <div className="px-2 py-1.5">
                  <div className="grid grid-cols-6 gap-1">
                    {SPEAKER_COLOR_OPTIONS.map((c) => (
                      <button
                        key={c.class}
                        onClick={() => handleColorSelect(c.class)}
                        className={`w-5 h-5 rounded-full border-2 ${
                          currentColor === c.class ? "border-white" : "border-transparent"
                        } hover:border-slate-300`}
                        style={{ backgroundColor: c.hex }}
                        title={c.name}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Cluster naming trigger */}
          {clusterId && onNameCluster && (
            <>
              <div className="border-t border-slate-600 my-1" />
              <button
                onClick={handleStartNaming}
                className="block w-full text-left px-3 py-1.5 text-sm text-emerald-400 hover:bg-slate-600"
              >
                名前を付ける...
              </button>
            </>
          )}
        </div>
      )}

      {/* Scope selection (single vs bulk) */}
      {pendingSpeaker && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-slate-700 border border-slate-600 rounded shadow-lg py-1 min-w-[10rem]">
          <div className="px-3 py-1.5 text-xs text-slate-400 border-b border-slate-600">
            → {pendingSpeaker.name}
          </div>
          <button
            onClick={() => handleScopeSelect("single")}
            className="block w-full text-left px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
          >
            この発言だけ
          </button>
          <button
            onClick={() => handleScopeSelect("bulk")}
            className="block w-full text-left px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-600"
          >
            同じ話者すべて変更
          </button>
        </div>
      )}

      {/* Inline cluster naming input with register/guest buttons */}
      {namingCluster && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-slate-700 border border-emerald-500 rounded shadow-lg p-2 min-w-[12rem]">
          <input
            ref={clusterInputRef}
            type="text"
            value={clusterName}
            onChange={(e) => setClusterName(e.target.value)}
            onKeyDown={handleClusterNameKeyDown}
            placeholder="話者名を入力"
            className="w-full bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-emerald-400"
          />
          <div className="flex gap-1.5 mt-1.5">
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleNameClusterSubmit(false)}
              disabled={!clusterName.trim()}
              className="flex-1 px-2 py-1 text-xs bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-600 disabled:text-slate-400 rounded text-white"
            >
              登録
            </button>
            <button
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => handleNameClusterSubmit(true)}
              disabled={!clusterName.trim()}
              className="flex-1 px-2 py-1 text-xs bg-amber-600 hover:bg-amber-700 disabled:bg-slate-600 disabled:text-slate-400 rounded text-white"
            >
              ゲスト
            </button>
          </div>
        </div>
      )}
    </span>
  );
}
