import { useState, useRef, useEffect } from "react";

interface Props {
  value: string;
  onChange: (query: string) => void;
}

export default function TranscriptSearch({ value, onChange }: Props) {
  const [localValue, setLocalValue] = useState(value);
  const composingRef = useRef(false);

  // Sync from parent when not composing
  useEffect(() => {
    if (!composingRef.current) {
      setLocalValue(value);
    }
  }, [value]);

  return (
    <div className="px-2 pt-2 shrink-0">
      <input
        value={localValue}
        onChange={(e) => {
          setLocalValue(e.target.value);
          if (!composingRef.current) {
            onChange(e.target.value);
          }
        }}
        onCompositionStart={() => { composingRef.current = true; }}
        onCompositionEnd={(e) => {
          composingRef.current = false;
          onChange(e.currentTarget.value);
        }}
        placeholder="検索..."
        className="bg-slate-700 border border-slate-600 rounded px-3 py-1 text-sm w-full"
      />
    </div>
  );
}
