interface Props {
  isRunning: boolean;
  isPaused: boolean;
  loading: boolean;
  sessionName: string;
  micDevice: string;
  loopbackDevice: string;
  onSessionNameChange: (name: string) => void;
  onStart: () => void;
  onPause: () => void;
  onStop: () => void;
}

export default function RecordingControls({
  isRunning,
  isPaused,
  loading,
  sessionName,
  micDevice,
  loopbackDevice,
  onSessionNameChange,
  onStart,
  onPause,
  onStop,
}: Props) {
  return (
    <div className="space-y-2">
      {/* Row 1: Active devices (auto-detected) */}
      {isRunning && (micDevice || loopbackDevice) && (
        <div className="flex items-center gap-3 text-xs text-slate-400">
          {micDevice && <span title="マイク">🎤 {micDevice}</span>}
          {loopbackDevice && <span title="ループバック">🔊 {loopbackDevice}</span>}
        </div>
      )}

      {/* Row 2: Session name + buttons */}
      <div className="flex items-center gap-3">
        <input
          value={sessionName}
          onChange={(e) => onSessionNameChange(e.target.value)}
          disabled={isRunning}
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="セッション名（省略可）"
        />

        {!isRunning ? (
          <button
            onClick={onStart}
            disabled={loading}
            className="px-5 py-1.5 bg-red-600 hover:bg-red-700 disabled:bg-slate-600 rounded text-sm font-medium transition-colors shrink-0"
          >
            {loading ? "開始中..." : "録音開始"}
          </button>
        ) : (
          <>
            <button
              onClick={onPause}
              className="px-4 py-1.5 bg-amber-600 hover:bg-amber-700 rounded text-sm transition-colors shrink-0"
            >
              {isPaused ? "再開" : "一時停止"}
            </button>
            <button
              onClick={onStop}
              disabled={loading}
              className="px-4 py-1.5 bg-red-700 hover:bg-red-800 disabled:bg-slate-600 rounded text-sm transition-colors shrink-0"
            >
              停止
            </button>
          </>
        )}
      </div>
    </div>
  );
}
