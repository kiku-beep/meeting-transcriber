import { useState, useCallback, useEffect } from "react";
import BackendLoader from "./components/BackendLoader";
import Transcription from "./components/Transcription";
import Speakers from "./components/Speakers";
import Dictionary from "./components/Dictionary";
import History from "./components/History";
import Settings from "./components/Settings";

const TABS = ["文字起こし", "話者", "辞書", "履歴", "設定"] as const;

export default function App() {
  const [backendReady, setBackendReady] = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [visitedTabs, setVisitedTabs] = useState<Set<number>>(new Set([0]));
  const [autoSummarizeSessionId, setAutoSummarizeSessionId] = useState<string | null>(null);

  const handleSessionStop = useCallback((sessionId: string) => {
    setAutoSummarizeSessionId(sessionId);
    setActiveTab(3); // History tab
  }, []);

  const handleAutoSummarizeComplete = useCallback(() => {
    setAutoSummarizeSessionId(null);
  }, []);

  useEffect(() => {
    setVisitedTabs(prev => {
      if (prev.has(activeTab)) return prev;
      return new Set(prev).add(activeTab);
    });
  }, [activeTab]);

  if (!backendReady) {
    return <BackendLoader onReady={() => setBackendReady(true)} />;
  }

  return (
    <div className="flex flex-col h-screen bg-slate-900 text-slate-100">
      {/* Tab Bar */}
      <nav className="flex border-b border-slate-700 bg-slate-800 shrink-0">
        {TABS.map((tab, i) => (
          <button
            key={tab}
            onClick={() => setActiveTab(i)}
            className={`px-5 py-3 text-sm font-medium transition-colors ${
              activeTab === i
                ? "text-cyan-400 border-b-2 border-cyan-400 bg-slate-900"
                : "text-slate-400 hover:text-slate-200 hover:bg-slate-700/50"
            }`}
          >
            {tab}
          </button>
        ))}
      </nav>

      {/* Tab Content — Tab 0 always mounted (WebSocket), others lazy-mounted on first visit */}
      <main className="flex-1 overflow-hidden">
        <div className={activeTab === 0 ? "h-full" : "hidden"}>
          <Transcription onSessionStop={handleSessionStop} />
        </div>
        {visitedTabs.has(1) && (
          <div className={activeTab === 1 ? "h-full" : "hidden"}>
            <Speakers />
          </div>
        )}
        {visitedTabs.has(2) && (
          <div className={activeTab === 2 ? "h-full" : "hidden"}>
            <Dictionary />
          </div>
        )}
        {visitedTabs.has(3) && (
          <div className={activeTab === 3 ? "h-full" : "hidden"}>
            <History
              autoSummarizeSessionId={autoSummarizeSessionId}
              onAutoSummarizeComplete={handleAutoSummarizeComplete}
            />
          </div>
        )}
        {visitedTabs.has(4) && (
          <div className={activeTab === 4 ? "h-full" : "hidden"}>
            <Settings />
          </div>
        )}
      </main>
    </div>
  );
}
