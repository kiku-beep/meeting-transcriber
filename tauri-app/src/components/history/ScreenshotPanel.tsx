import { useMemo, useRef, useState, useEffect } from "react";
import { listScreenshots, getScreenshotUrl } from "../../lib/apiScreenshots";
import type { ScreenshotInfo } from "../../lib/types";
import ScreenshotThumbnail from "./ScreenshotThumbnail";
import ScreenshotModal from "./ScreenshotModal";

interface Props {
  sessionId: string;
  activeTimeSeconds?: number | null;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

function findNearestScreenshotIndex(
  screenshots: ScreenshotInfo[],
  activeTimeSeconds?: number | null,
): number | null {
  if (activeTimeSeconds === null || activeTimeSeconds === undefined || screenshots.length === 0) {
    return null;
  }

  let nearestIndex = 0;
  let nearestDistance = Math.abs(screenshots[0].relative_seconds - activeTimeSeconds);
  for (let i = 1; i < screenshots.length; i += 1) {
    const distance = Math.abs(screenshots[i].relative_seconds - activeTimeSeconds);
    if (distance < nearestDistance) {
      nearestDistance = distance;
      nearestIndex = i;
    }
  }
  return nearestIndex;
}

export default function ScreenshotPanel({ sessionId, activeTimeSeconds }: Props) {
  const [screenshots, setScreenshots] = useState<ScreenshotInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const thumbnailRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const targetScrollTopRef = useRef<number | null>(null);
  const animationFrameRef = useRef<number | null>(null);

  const activeIndex = useMemo(
    () => findNearestScreenshotIndex(screenshots, activeTimeSeconds),
    [screenshots, activeTimeSeconds],
  );

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

  const animateToTarget = () => {
    const scroller = scrollerRef.current;
    const target = targetScrollTopRef.current;
    if (!scroller || target === null) {
      animationFrameRef.current = null;
      return;
    }

    const delta = target - scroller.scrollTop;
    if (Math.abs(delta) < 0.5) {
      scroller.scrollTop = target;
      animationFrameRef.current = null;
      return;
    }

    scroller.scrollTop += delta * 0.28;
    animationFrameRef.current = requestAnimationFrame(animateToTarget);
  };

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (
      !scroller ||
      activeTimeSeconds === null ||
      activeTimeSeconds === undefined ||
      screenshots.length === 0
    ) {
      return;
    }

    let lowerIndex = 0;
    let upperIndex = screenshots.length - 1;
    for (let i = 0; i < screenshots.length; i += 1) {
      if (screenshots[i].relative_seconds <= activeTimeSeconds) {
        lowerIndex = i;
      }
      if (screenshots[i].relative_seconds >= activeTimeSeconds) {
        upperIndex = i;
        break;
      }
    }

    const lowerElement = thumbnailRefs.current[lowerIndex];
    const upperElement = thumbnailRefs.current[upperIndex];
    if (!lowerElement || !upperElement) return;

    const lowerCenter = lowerElement.offsetTop + lowerElement.offsetHeight / 2;
    const upperCenter = upperElement.offsetTop + upperElement.offsetHeight / 2;
    const lowerTime = screenshots[lowerIndex].relative_seconds;
    const upperTime = screenshots[upperIndex].relative_seconds;
    const timeSpan = upperTime - lowerTime;
    const ratio = timeSpan === 0 ? 0 : (activeTimeSeconds - lowerTime) / timeSpan;
    const contentAnchor = lowerCenter + (upperCenter - lowerCenter) * Math.max(0, Math.min(1, ratio));
    const viewportAnchor = Math.min(scroller.clientHeight * 0.35, 160);
    const maxScrollTop = Math.max(0, scroller.scrollHeight - scroller.clientHeight);
    const target = Math.max(0, Math.min(maxScrollTop, contentAnchor - viewportAnchor));

    targetScrollTopRef.current = target;
    if (animationFrameRef.current === null) {
      animationFrameRef.current = requestAnimationFrame(animateToTarget);
    }
  }, [activeTimeSeconds, screenshots]);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) {
        cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

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
      <div className="screenshot-panel flex flex-col h-full">
        <div className="screenshot-panel__header px-3 py-2 shrink-0">
          <h3 className="screenshot-panel__title text-xs font-medium">
            スクリーンショット ({screenshots.length}枚)
          </h3>
        </div>
        <div ref={scrollerRef} className="flex-1 overflow-y-auto p-2 space-y-1">
          {screenshots.map((ss, i) => (
            <ScreenshotThumbnail
              key={ss.filename}
              ref={(element) => {
                thumbnailRefs.current[i] = element;
              }}
              screenshot={ss}
              imageUrl={getScreenshotUrl(sessionId, ss.filename)}
              active={activeIndex === i}
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
