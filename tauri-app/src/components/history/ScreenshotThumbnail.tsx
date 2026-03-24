import type { ScreenshotInfo } from "../../lib/types";

interface Props {
  screenshot: ScreenshotInfo;
  imageUrl: string;
  onClick: () => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function ScreenshotThumbnail({ screenshot, imageUrl, onClick }: Props) {
  return (
    <button
      onClick={onClick}
      className="group w-full flex flex-col items-center gap-1 p-1.5 rounded hover:bg-slate-700/50 transition-colors"
    >
      <img
        src={imageUrl}
        alt={`Screenshot at ${formatTime(screenshot.relative_seconds)}`}
        className="w-full rounded border border-slate-700 group-hover:border-cyan-500 transition-colors"
        loading="lazy"
      />
      <span className="text-xs text-slate-400 tabular-nums">
        {formatTime(screenshot.relative_seconds)}
      </span>
    </button>
  );
}
