import { forwardRef } from "react";
import type { ScreenshotInfo } from "../../lib/types";

interface Props {
  screenshot: ScreenshotInfo;
  imageUrl: string;
  onClick: () => void;
  active?: boolean;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

const ScreenshotThumbnail = forwardRef<HTMLButtonElement, Props>(function ScreenshotThumbnail(
  { screenshot, imageUrl, onClick, active = false },
  ref,
) {
  return (
    <button
      ref={ref}
      onClick={onClick}
      aria-current={active ? "time" : undefined}
      className={`screenshot-thumbnail group w-full flex flex-col items-center gap-1 p-1.5 rounded ${active ? "screenshot-thumbnail--active" : ""}`}
    >
      <img
        src={imageUrl}
        alt={`Screenshot at ${formatTime(screenshot.relative_seconds)}`}
        className={`screenshot-thumbnail__image w-full aspect-video object-cover rounded border ${active ? "screenshot-thumbnail__image--active" : ""}`}
        loading="lazy"
      />
      <span className={`screenshot-thumbnail__time text-xs tabular-nums ${active ? "screenshot-thumbnail__time--active" : ""}`}>
        {formatTime(screenshot.relative_seconds)}
      </span>
    </button>
  );
});

export default ScreenshotThumbnail;
