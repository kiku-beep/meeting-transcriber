import { useCallback, useEffect, useState } from "react";
import { getSpeakers, deleteSpeaker, createSpeakerNameOnly, addSpeakerSamples, recomputeEmbedding, recomputeAll, renameSpeaker } from "../lib/apiSpeakers";
import type { Speaker } from "../lib/types";

export default function Speakers() {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [name, setName] = useState("");
  const [registering, setRegistering] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [renamingId, setRenamingId] = useState<string | null>(null);

  const refresh = useCallback(async (showLoading = true) => {
    if (showLoading) setLoading(true);
    try {
      const data = await getSpeakers();
      setSpeakers(data.speakers);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (showLoading) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (!error) return;
    const retryTimer = window.setInterval(() => {
      void refresh(false);
    }, 2000);
    return () => window.clearInterval(retryTimer);
  }, [error, refresh]);

  const handleCreateNameOnly = async () => {
    if (!name.trim()) {
      setError("名前を入力してください");
      return;
    }
    setRegistering(true);
    setError("");
    try {
      await createSpeakerNameOnly(name.trim());
      setName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRegistering(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm("この話者を削除しますか？")) return;
    try {
      await deleteSpeaker(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRecompute = async (id: string) => {
    try {
      await recomputeEmbedding(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleRecomputeAll = async () => {
    try {
      await recomputeAll();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleStartRename = (s: Speaker) => {
    setEditingId(s.id);
    setEditName(s.name);
    setError("");
  };

  const handleRename = async (id: string) => {
    const trimmedName = editName.trim();
    if (!trimmedName) {
      setError("話者名を入力してください");
      return;
    }
    setRenamingId(id);
    setError("");
    try {
      const result = await renameSpeaker(id, trimmedName);
      setSpeakers((current) => current.map((speaker) => (
        speaker.id === id ? result.speaker : speaker
      )));
      setEditingId(null);
      setEditName("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRenamingId(null);
    }
  };

  const handleAddSamples = async (id: string) => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".wav";
    input.multiple = true;
    input.onchange = async () => {
      const files = input.files;
      if (!files?.length) return;
      try {
        await addSpeakerSamples(id, Array.from(files));
        await refresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    };
    input.click();
  };

  const needsRecompute = speakers.some((s) => !s.has_embedding && s.sample_count > 0);

  return (
    <div className="workspace-page overflow-y-auto h-full">
      <header className="page-heading">
        <div><p className="workspace-eyebrow">SPEAKER PROFILES</p><h2>話者管理</h2></div>
        <span className="page-heading__meta">{speakers.length}人登録</span>
      </header>

      {error && (
        <div role="alert" className="inline-alert inline-alert--error flex items-center justify-between">
          <span>{error}</span>
          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={() => void refresh()}
              disabled={loading}
              className="inline-alert__action px-2 py-1"
            >
              {loading ? "読み込み中" : "再読み込み"}
            </button>
            <button
              onClick={() => setError("")}
              className="inline-alert__dismiss"
              aria-label="エラーを閉じる"
            >
              &#x2715;
            </button>
          </div>
        </div>
      )}

      {/* Register */}
      <section className="space-y-3">
        <h3 className="text-sm font-medium text-slate-300">話者登録</h3>

        {/* Name-only registration */}
        <div className="p-3 bg-slate-800/50 border border-slate-700 rounded space-y-2">
          <p className="text-xs text-slate-400">名前だけで登録（音声なし）</p>
          <div className="flex items-end gap-3">
            <div>
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="bg-slate-700 border border-slate-600 rounded px-3 py-1.5 text-sm w-48"
                placeholder="話者名"
              />
            </div>
            <button
              onClick={handleCreateNameOnly}
              disabled={registering}
              className="px-4 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:bg-slate-600 rounded text-sm transition-colors"
            >
              {registering ? "作成中..." : "名前のみで作成"}
            </button>
          </div>
          <p className="text-xs text-slate-500">
            会議参加者として期待話者に設定できます。後で音声を追加することも可能です。
          </p>
        </div>

      </section>

      {/* Speaker List */}
      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium text-slate-300">
            登録済み話者 ({speakers.length}人)
          </h3>
          {needsRecompute && (
            <button
              onClick={handleRecomputeAll}
              className="px-3 py-1 bg-yellow-600 hover:bg-yellow-700 rounded text-xs transition-colors"
            >
              全て再計算
            </button>
          )}
        </div>
        {loading ? (
          <p className="text-sm text-slate-500">話者を読み込んでいます...</p>
        ) : speakers.length === 0 ? (
          <p className="text-sm text-slate-500">話者が登録されていません</p>
        ) : (
          <div className="space-y-2">
            {speakers.map((s) => (
              <div
                key={s.id}
                className="speaker-row"
              >
                <div className="speaker-row__identity">
                  {editingId === s.id ? (
                    <div className="speaker-rename">
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleRename(s.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        autoFocus
                        aria-label={`${s.name}の新しい名前`}
                        className="speaker-rename__input"
                      />
                      <button
                        onClick={() => handleRename(s.id)}
                        disabled={renamingId === s.id}
                        className="speaker-action speaker-action--primary"
                      >
                        {renamingId === s.id ? "保存中" : "保存"}
                      </button>
                      <button
                        onClick={() => setEditingId(null)}
                        disabled={renamingId === s.id}
                        className="speaker-action"
                      >
                        キャンセル
                      </button>
                    </div>
                  ) : (
                    <span className="speaker-row__name">{s.name}</span>
                  )}
                  <span className="text-slate-400 text-sm">サンプル: {s.sample_count}個</span>
                  {s.has_embedding ? (
                    <span className="text-emerald-400 text-xs">&#x2713; 登録済</span>
                  ) : s.sample_count > 0 ? (
                    <span className="text-yellow-400 text-xs">要再計算</span>
                  ) : (
                    <span className="text-slate-500 text-xs">音声未登録</span>
                  )}
                </div>
                <div className="speaker-row__actions">
                  {editingId !== s.id && (
                    <button
                      onClick={() => handleStartRename(s)}
                      className="speaker-action"
                      aria-label={`${s.name}の名前を変更`}
                    >
                      名前変更
                    </button>
                  )}
                  {!s.has_embedding && s.sample_count > 0 && (
                    <button
                      onClick={() => handleRecompute(s.id)}
                      className="text-yellow-400 hover:text-yellow-300 text-sm"
                    >
                      再計算
                    </button>
                  )}
                  {s.sample_count === 0 && (
                    <button
                      onClick={() => handleAddSamples(s.id)}
                      className="text-cyan-400 hover:text-cyan-300 text-sm"
                    >
                      音声追加
                    </button>
                  )}
                  <button
                    onClick={() => handleDelete(s.id)}
                    className="speaker-action speaker-action--danger"
                  >
                    削除
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
