import { useState } from "react";
import { testDictionary } from "../../lib/apiDictionary";

export default function DictionaryTester() {
  const [testInput, setTestInput] = useState("");
  const [testResult, setTestResult] = useState("");

  const handleTest = async () => {
    if (!testInput) return;
    try {
      const result = await testDictionary(testInput);
      setTestResult(JSON.stringify(result, null, 2));
    } catch (e) {
      setTestResult(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <section className="space-y-3">
      <h3 className="text-sm font-medium text-slate-300">辞書テスト</h3>
      <div className="flex gap-2">
        <input
          value={testInput}
          onChange={(e) => setTestInput(e.target.value)}
          className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm flex-1"
          placeholder="テストしたいテキスト"
          onKeyDown={(e) => { if (!e.nativeEvent.isComposing && e.keyCode !== 229 && e.key === "Enter") handleTest(); }}
        />
        <button
          onClick={handleTest}
          className="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-700 rounded text-sm transition-colors"
        >
          テスト
        </button>
      </div>
      {testResult && (
        <pre className="bg-slate-800 border border-slate-700 rounded p-3 text-sm text-slate-300 overflow-x-auto">
          {testResult}
        </pre>
      )}
    </section>
  );
}
