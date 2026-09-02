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
    return <div className="workspace-page"><div className="workspace-loading">辞書を読み込んでいます</div></div>;
  }

  return (
    <div className="workspace-page overflow-y-auto h-full">
      <header className="page-heading">
        <div><p className="workspace-eyebrow">LANGUAGE RULES</p><h2>辞書</h2></div>
        <span className="page-heading__meta">{dict.replacements.length}ルール</span>
      </header>

      {error && (
        <div className="inline-alert inline-alert--error flex items-center justify-between" role="alert">
          <span>{error}</span>
          <button onClick={() => setError("")} className="inline-alert__dismiss ml-2 shrink-0">&#x2715;</button>
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
