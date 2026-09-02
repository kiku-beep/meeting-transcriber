import type { AudioPlayerState, AudioPlayerActions } from "../../lib/useAudioPlayer";

interface Props {
  state: AudioPlayerState;
  actions: AudioPlayerActions;
  onDeleteAudio?: () => void;
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

const RATES = [0.5, 1, 1.5, 2];

export default function PlayerBar({ state, actions, onDeleteAudio }: Props) {
  const { isPlaying, isLoading, currentTime, duration, playbackRate } = state;

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    actions.seekTo(Number(e.target.value));
  };

  const cycleRate = () => {
    const idx = RATES.indexOf(playbackRate);
    const next = RATES[(idx + 1) % RATES.length];
    actions.setPlaybackRate(next);
  };

  const handleDelete = () => {
    if (confirm("音声ファイルを削除しますか？\nこの操作は取り消せません。")) {
      onDeleteAudio?.();
    }
  };

  return (
    <div data-testid="player-bar" className="player-bar flex items-center gap-3 px-4 py-2 shrink-0">
      {/* Play/Pause */}
      <button
        data-testid="player-toggle"
        onClick={() => actions.toggle()}
        className="player-bar__toggle text-lg w-8 h-8 flex items-center justify-center rounded disabled:opacity-40 disabled:cursor-not-allowed"
        title={isLoading ? "読み込み中" : isPlaying ? "一時停止" : "再生"}
        disabled={isLoading}
      >
        {isLoading ? (
          <span className="animate-pulse text-sm">...</span>
        ) : isPlaying ? "⏸" : "▶"}
      </button>

      {/* Time */}
      <span data-testid="player-time" className="player-bar__time text-xs tabular-nums w-24 text-center shrink-0">
        {isLoading ? "読込中..." : `${formatTime(currentTime)} / ${formatTime(duration)}`}
      </span>

      {/* Seek bar */}
      <input
        data-testid="player-seek"
        type="range"
        min={0}
        max={duration || 0}
        step={0.1}
        value={currentTime}
        onChange={handleSeek}
        className="player-bar__seek flex-1 h-1.5 cursor-pointer disabled:opacity-40"
        disabled={isLoading}
      />

      {/* Playback rate */}
      <button
        data-testid="player-rate"
        onClick={cycleRate}
        className="player-bar__rate text-xs px-2 py-1 rounded tabular-nums min-w-[3rem]"
        title="再生速度"
      >
        {playbackRate}x
      </button>

      {/* Delete audio */}
      {onDeleteAudio && (
        <button
          data-testid="player-delete"
          onClick={handleDelete}
          className="player-bar__delete text-xs px-2 py-1 rounded"
          title="音声削除"
        >
          音声削除
        </button>
      )}
    </div>
  );
}
