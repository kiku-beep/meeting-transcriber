import { useState, useRef, useEffect, type ReactNode } from "react";

function highlightText(text: string, query: string): ReactNode {
  if (!query) return text;
  const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
  return parts.map((part, i) =>
    part.toLowerCase() === query.toLowerCase()
      ? <mark key={i} className="bg-yellow-500/30 text-inherit">{part}</mark>
      : part
  );
}

interface Props {
  text: string;
  entryId: string;
  searchQuery?: string;
  onEditText?: (entryId: string, newText: string) => Promise<void>;
  onSavingChange: (saving: boolean) => void;
}

export default function EntryEditor({ text, entryId, searchQuery, onEditText, onSavingChange }: Props) {
  const [editingText, setEditingText] = useState(false);
  const [editText, setEditText] = useState(text);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const savingRef = useRef(false);

  // Focus textarea when entering edit mode
  useEffect(() => {
    if (editingText && textRef.current) {
      textRef.current.focus();
      textRef.current.selectionStart = textRef.current.value.length;
    }
  }, [editingText]);

  const handleTextClick = () => {
    if (!onEditText) return;
    setEditText(text);
    setEditingText(true);
  };

  const handleTextSave = async () => {
    if (savingRef.current) return;
    if (!onEditText || editText === text) {
      setEditingText(false);
      return;
    }
    savingRef.current = true;
    onSavingChange(true);
    try {
      await onEditText(entryId, editText);
    } finally {
      savingRef.current = false;
      onSavingChange(false);
      setEditingText(false);
    }
  };

  const handleTextKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleTextSave();
    } else if (e.key === "Escape") {
      setEditingText(false);
    }
  };

  if (editingText) {
    return (
      <div className="flex-1 flex gap-1">
        <textarea
          ref={textRef}
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          onKeyDown={handleTextKeyDown}
          onBlur={handleTextSave}
          rows={Math.max(1, Math.ceil(editText.length / 60))}
          className="flex-1 bg-slate-700 border border-cyan-500 rounded px-2 py-0.5 text-sm text-slate-200 resize-none focus:outline-none"
        />
      </div>
    );
  }

  return (
    <span
      className={`text-slate-200 ${onEditText ? "cursor-pointer hover:bg-slate-700/50 rounded px-1 -mx-1" : ""}`}
      onClick={handleTextClick}
      title={onEditText ? "クリックで編集" : undefined}
    >
      {searchQuery ? highlightText(text, searchQuery) : text}
    </span>
  );
}
