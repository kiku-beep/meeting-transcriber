import { useEffect, useState } from "react";
import { getDictionary, deleteReplacement } from "../lib/apiDictionary";
import type { DictionaryConfig } from "../lib/types";
import LearningSuggestions from "./dictionary/LearningSuggestions";
import RuleForm from "./dictionary/RuleForm";
import RuleList from "./dictionary/RuleList";
import FillerSettings from "./dictionary/FillerSettings";
import DictionaryTester from "./dictionary/DictionaryTester";

export default function Dictionary() {
  const [dict, setDict] = useState<DictionaryConfig | null>(null);
  const [error, setError] = useState("");

  const refresh = async () => {
    try {
      const data = await getDictionary();
      setDict(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  const handleDelete = async (index: number) => {
    try {
      await deleteReplacement(index);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!dict) {
    return <div className="p-6 text-slate-400 text-sm">読み込み中…</div>;
  }

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <h2 className="text-lg font-semibold">辞書設定</h2>

      {error && (
        <div className="p-3 bg-red-900/50 border border-red-700 rounded text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-300 ml-2 shrink-0">&#x2715;</button>
        </div>
      )}

      <LearningSuggestions onRefresh={refresh} />
      <RuleForm onAdd={refresh} />
      <RuleList replacements={dict.replacements} onDelete={handleDelete} onRefresh={refresh} />
      <FillerSettings
        initialFillers={dict.fillers}
        initialEnabled={dict.filler_removal_enabled}
        onSave={refresh}
      />
      <DictionaryTester />
    </div>
  );
}
