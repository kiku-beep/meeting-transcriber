import { useEffect } from "react";

interface Props {
  imageUrl: string;
  timestamp: string;
  onClose: () => void;
}

export default function ScreenshotModal({ imageUrl, timestamp, onClose }: Props) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      onClick={onClose}
    >
      <div
        className="relative max-w-[90vw] max-h-[90vh]"
        onClick={(e) => e.stopPropagation()}
      >
        <img
          src={imageUrl}
          alt={`Screenshot at ${timestamp}`}
          className="max-w-full max-h-[85vh] rounded-lg shadow-2xl"
        />
        <div className="absolute top-2 right-2 flex items-center gap-2">
          <span className="text-xs text-slate-300 bg-black/60 px-2 py-1 rounded">
            {timestamp}
          </span>
          <button
            onClick={onClose}
            className="text-slate-300 hover:text-white bg-black/60 hover:bg-black/80 rounded px-2 py-1 text-sm transition-colors"
          >
            &#x2715;
          </button>
        </div>
      </div>
    </div>
  );
}
