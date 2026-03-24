const STORAGE_KEY = "transcriber_speaker_colors";

export const SPEAKER_COLOR_OPTIONS = [
  { name: "シアン", class: "text-cyan-400", hex: "#22d3ee" },
  { name: "エメラルド", class: "text-emerald-400", hex: "#34d399" },
  { name: "アンバー", class: "text-amber-400", hex: "#fbbf24" },
  { name: "バイオレット", class: "text-violet-400", hex: "#a78bfa" },
  { name: "ローズ", class: "text-rose-400", hex: "#fb7185" },
  { name: "ブルー", class: "text-blue-400", hex: "#60a5fa" },
  { name: "オレンジ", class: "text-orange-400", hex: "#fb923c" },
  { name: "ピンク", class: "text-pink-400", hex: "#f472b6" },
  { name: "ライム", class: "text-lime-400", hex: "#a3e635" },
  { name: "ティール", class: "text-teal-400", hex: "#2dd4bf" },
  { name: "インディゴ", class: "text-indigo-400", hex: "#818cf8" },
  { name: "レッド", class: "text-red-400", hex: "#f87171" },
];

const FALLBACK_COLORS = SPEAKER_COLOR_OPTIONS.map((c) => c.class);

export function getSavedSpeakerColor(speakerName: string): string | null {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return null;
    const map: Record<string, string> = JSON.parse(stored);
    return map[speakerName] ?? null;
  } catch {
    return null;
  }
}

export function saveSpeakerColor(speakerName: string, colorClass: string): void {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    const map: Record<string, string> = stored ? JSON.parse(stored) : {};
    map[speakerName] = colorClass;
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore
  }
}

export function getDefaultSpeakerColor(speakerName: string): string {
  let hash = 0;
  for (let i = 0; i < speakerName.length; i++) {
    hash = (hash * 31 + speakerName.charCodeAt(i)) | 0;
  }
  return FALLBACK_COLORS[Math.abs(hash) % FALLBACK_COLORS.length];
}
