import { useState, useEffect } from "react";
import { listScreenshots, getScreenshotUrl } from "../../lib/apiScreenshots";
import type { ScreenshotInfo } from "../../lib/types";
import ScreenshotThumbnail from "./ScreenshotThumbnail";
import ScreenshotModal from "./ScreenshotModal";

interface Props {
  sessionId: string;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export default function ScreenshotPanel({ sessionId }: Props) {
  const [screenshots, setScreenshots] = useState<ScreenshotInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setScreenshots([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    listScreenshots(sessionId)
      .then((data) => setScreenshots(data.screenshots))
      .catch(() => setScreenshots([]))
      .finally(() => setLoading(false));
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm">
        読み込み中...
      </div>
    );
  }

  if (screenshots.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500 text-sm px-4 text-center">
        スクリーンショットなし
      </div>
    );
  }

  const selected = selectedIndex !== null ? screenshots[selectedIndex] : null;

  return (
    <>
      <div className="flex flex-col h-full">
        <div className="px-3 py-2 border-b border-slate-700 shrink-0">
          <h3 className="text-xs font-medium text-slate-400">
            スクリーンショット ({screenshots.length}枚)
          </h3>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {screenshots.map((ss, i) => (
            <ScreenshotThumbnail
              key={ss.filename}
              screenshot={ss}
              imageUrl={getScreenshotUrl(sessionId, ss.filename)}
              onClick={() => setSelectedIndex(i)}
            />
          ))}
        </div>
      </div>

      {selected && (
        <ScreenshotModal
          imageUrl={getScreenshotUrl(sessionId, selected.filename)}
          timestamp={formatTime(selected.relative_seconds)}
          onClose={() => setSelectedIndex(null)}
        />
      )}
    </>
  );
}
