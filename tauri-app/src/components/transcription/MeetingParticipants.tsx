import { useState, useRef } from "react";
import type { Speaker } from "../../lib/types";

interface Props {
  visible: boolean;
  speakers?: Speaker[];
  onSubmit: (names: string[], speakerIds: string[]) => Promise<void>;
}

export default function MeetingParticipants({ visible, speakers, onSubmit }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [input, setInput] = useState("");
  const [participants, setParticipants] = useState<{ name: string; speakerId?: string }[]>([]);
  const [submitted, setSubmitted] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  if (!visible) return null;

  const handleAdd = () => {
    const name = input.trim();
    if (!name || participants.some((p) => p.name === name)) return;
    setParticipants((prev) => [...prev, { name }]);
    setInput("");
    inputRef.current?.focus();
  };

  const handleAddRegistered = (speaker: Speaker) => {
    if (participants.some((p) => p.speakerId === speaker.id || p.name === speaker.name)) return;
    setParticipants((prev) => [...prev, { name: speaker.name, speakerId: speaker.id }]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.nativeEvent.isComposing) return;
      handleAdd();
    }
  };

  const handleRemove = (name: string) => {
    setParticipants((prev) => prev.filter((p) => p.name !== name));
  };

  const handleSubmit = async () => {
    if (participants.length === 0) return;
    const names = participants.map((p) => p.name);
    const speakerIds = participants.filter((p) => p.speakerId).map((p) => p.speakerId!);
    await onSubmit(names, speakerIds);
    setSubmitted(true);
  };

  const handleReset = async () => {
    setParticipants([]);
    setSubmitted(false);
    await onSubmit([], []);
  };

  const registeredNotAdded = (speakers || []).filter(
    (s) => !participants.some((p) => p.speakerId === s.id || p.name === s.name)
  );

  return (
    <div className="text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="text-slate-400 hover:text-slate-300 flex items-center gap-1"
      >
        <span className={`transition-transform ${expanded ? "rotate-90" : ""}`}>&#9656;</span>
        会議参加者
        {participants.length > 0 && (
          <span className="text-emerald-400 ml-1">({participants.length}名)</span>
        )}
      </button>

      {expanded && (
        <div className="mt-2 space-y-2">
          {/* Registered speaker picker */}
          {!submitted && registeredNotAdded.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {registeredNotAdded.map((s) => (
                <button
                  key={s.id}
                  onClick={() => handleAddRegistered(s)}
                  className="inline-flex items-center gap-1 bg-cyan-900/40 text-cyan-300 border border-cyan-700/50 rounded px-2 py-0.5 hover:bg-cyan-800/50 text-xs"
                >
                  + {s.name}
                </button>
              ))}
            </div>
          )}

          {/* Participant chips */}
          {participants.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {participants.map((p) => (
                <span
                  key={p.name}
                  className={`inline-flex items-center gap-1 rounded px-2 py-0.5 ${
                    p.speakerId ? "bg-cyan-900/30 text-cyan-200" : "bg-slate-700 text-slate-200"
                  }`}
                >
                  {p.name}
                  {!submitted && (
                    <button
                      onClick={() => handleRemove(p.name)}
                      className="text-slate-400 hover:text-red-400"
                    >
                      &#x2715;
                    </button>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* Input */}
          {!submitted && (
            <div className="flex gap-1">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="参加者名を入力"
                className="flex-1 bg-slate-800 border border-slate-600 rounded px-2 py-1 text-sm text-slate-200 focus:outline-none focus:border-cyan-500"
              />
              <button
                onClick={handleAdd}
                disabled={!input.trim()}
                className="px-2 py-1 bg-slate-700 text-slate-300 rounded hover:bg-slate-600 disabled:opacity-40"
              >
                追加
              </button>
              {participants.length > 0 && (
                <button
                  onClick={handleSubmit}
                  className="px-2 py-1 bg-emerald-700 text-emerald-100 rounded hover:bg-emerald-600"
                >
                  設定
                </button>
              )}
            </div>
          )}

          {/* Submitted state */}
          {submitted && (
            <div className="flex items-center gap-2">
              <span className="text-emerald-400">設定済み</span>
              <button
                onClick={handleReset}
                className="text-slate-400 hover:text-slate-300 text-xs"
              >
                リセット
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
