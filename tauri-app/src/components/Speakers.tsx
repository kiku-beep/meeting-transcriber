import { useEffect, useState } from "react";
import { getSpeakers, deleteSpeaker, createSpeakerNameOnly, addSpeakerSamples, recomputeEmbedding, recomputeAll, renameSpeaker } from "../lib/apiSpeakers";
import type { Speaker } from "../lib/types";

export default function Speakers() {
  const [speakers, setSpeakers] = useState<Speaker[]>([]);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [registering, setRegistering] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");


  const refresh = async () => {
    try {
      const data = await getSpeakers();
      setSpeakers(data.speakers);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  useEffect(() => {
    refresh();
  }, []);

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
  };

  const handleRename = async (id: string) => {
    if (!editName.trim()) return;
    try {
      await renameSpeaker(id, editName.trim());
      setEditingId(null);
      setEditName("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
    <div className="p-6 space-y-6 overflow-y-auto h-full">
      <h2 className="text-lg font-semibold">話者管理</h2>

      {error && (
        <div className="p-3 bg-red-900/50 border border-red-700 rounded text-red-300 text-sm flex items-center justify-between">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-300 ml-2 shrink-0">&#x2715;</button>
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
        {speakers.length === 0 ? (
          <p className="text-sm text-slate-500">話者が登録されていません</p>
        ) : (
          <div className="space-y-2">
            {speakers.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between p-3 bg-slate-800 rounded border border-slate-700"
              >
                <div className="flex items-center gap-3">
                  {editingId === s.id ? (
                    <div className="flex items-center gap-1">
                      <input
                        value={editName}
                        onChange={(e) => setEditName(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") handleRename(s.id);
                          if (e.key === "Escape") setEditingId(null);
                        }}
                        autoFocus
                        className="bg-slate-700 border border-cyan-500 rounded px-2 py-0.5 text-sm w-36"
                      />
                      <button
                        onClick={() => handleRename(s.id)}
                        className="text-emerald-400 hover:text-emerald-300 text-sm"
                      >
                        ✓
                      </button>
                      <button
                        onClick={() => setEditingId(null)}
                        className="text-slate-400 hover:text-slate-300 text-sm"
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <span
                      className="font-medium cursor-pointer hover:text-cyan-400 transition-colors"
                      onClick={() => handleStartRename(s)}
                      title="クリックで名前を変更"
                    >
                      {s.name}
                    </span>
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
                <div className="flex items-center gap-2">
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
                    className="text-red-400 hover:text-red-300 text-sm"
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
