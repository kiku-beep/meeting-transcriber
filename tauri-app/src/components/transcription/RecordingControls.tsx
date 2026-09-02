interface Props {
  isRunning: boolean;
  isPaused: boolean;
  loading: boolean;
  sessionName: string;
  micDevice: string;
  loopbackDevice: string;
  elapsedSeconds: number;
  aiOpen: boolean;
  onSessionNameChange: (name: string) => void;
  onStart: () => void;
  onPause: () => void;
  onStop: () => void;
  onDiscard: () => void;
  onAiToggle: () => void;
}

export default function RecordingControls({
  isRunning,
  isPaused,
  loading,
  sessionName,
  micDevice,
  loopbackDevice,
  elapsedSeconds,
  aiOpen,
  onSessionNameChange,
  onStart,
  onPause,
  onStop,
  onDiscard,
  onAiToggle,
}: Props) {
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = Math.floor(elapsedSeconds % 60);
  const elapsed = `${minutes}:${String(seconds).padStart(2, "0")}`;

  return (
    <div className="recording-bar">
      <div className="recording-state" title={[micDevice, loopbackDevice].filter(Boolean).join(" / ")}>
        <span className={`recording-dot ${isRunning ? "recording-dot--active" : ""}`} aria-hidden="true" />
        <span>{isRunning ? (isPaused ? "一時停止" : "録音中") : "待機中"}</span>
        {isRunning && <span className="recording-elapsed">{elapsed}</span>}
      </div>
        <input
          value={sessionName}
          onChange={(e) => onSessionNameChange(e.target.value)}
          className="recording-name"
          placeholder="セッション名（省略可）"
        />

        {!isRunning ? (
          <button
            onClick={onStart}
            disabled={loading}
            className="control-button control-button--record"
          >
            {loading ? "開始中..." : "録音開始"}
          </button>
        ) : (
          <>
            <button
              onClick={onPause}
              className="control-button"
            >
              <span aria-hidden="true">Ⅱ</span> {isPaused ? "再開" : "一時停止"}
            </button>
            <button
              onClick={onStop}
              disabled={loading}
              className="control-button"
            >
              <span aria-hidden="true">□</span> 停止
            </button>
            <button
              type="button"
              onClick={onDiscard}
              className="control-button control-button--discard"
              aria-label="録音を破棄"
            >
              破棄
            </button>
          </>
        )}
      <button
        type="button"
        className={`control-button control-button--ai ${aiOpen ? "is-active" : ""}`}
        aria-label="AIアシスト"
        aria-expanded={aiOpen}
        onClick={onAiToggle}
      >
        <span aria-hidden="true">✣</span> AI
      </button>
    </div>
  );
}
