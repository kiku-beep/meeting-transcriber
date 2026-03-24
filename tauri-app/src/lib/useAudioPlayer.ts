import { useCallback, useEffect, useRef, useState } from "react";
import type { TranscriptEntry } from "./types";

interface AudioDebugAPI {
  isPlaying: () => boolean;
  getGapCount: () => number;
  getGapLog: () => Array<{ time: number; durationMs: number }>;
  getBufferDuration: () => number;
  getCurrentTime: () => number;
  getBuffered: () => Array<{ start: number; end: number }>;
  getReadyState: () => number;
  getNetworkState: () => number;
  resetGaps: () => void;
}

declare global {
  interface Window {
    __audioDebug?: AudioDebugAPI;
  }
}

export interface AudioPlayerState {
  isPlaying: boolean;
  isLoading: boolean;
  currentTime: number;
  duration: number;
  playbackRate: number;
  currentEntryId: string | null;
}

export interface AudioPlayerActions {
  play: (fromSeconds?: number) => void;
  pause: () => void;
  toggle: () => void;
  seekTo: (seconds: number) => void;
  setPlaybackRate: (rate: number) => void;
  setSource: (url: string) => void;
  setLoading: (loading: boolean) => void;
  destroy: () => void;
}

export function useAudioPlayer(entries: TranscriptEntry[]): [AudioPlayerState, AudioPlayerActions] {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const blobUrlRef = useRef<string | null>(null);
  const isPlayingRef = useRef(false);
  const generationRef = useRef(0);

  // Gap detection via stall monitoring
  const gapCountRef = useRef(0);
  const gapLogRef = useRef<Array<{ time: number; durationMs: number }>>([]);
  const stallCheckRef = useRef<number>(0);
  const lastTimeRef = useRef(0);
  const lastCheckRef = useRef(0);

  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackRate, setPlaybackRateState] = useState(1);
  const [currentEntryId, setCurrentEntryId] = useState<string | null>(null);
  const entriesRef = useRef(entries);
  entriesRef.current = entries;

  // --- helpers ---

  function cleanupAudio() {
    stopStallDetection();
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute("src");
      audioRef.current.load();
      audioRef.current = null;
    }
    if (blobUrlRef.current) {
      URL.revokeObjectURL(blobUrlRef.current);
      blobUrlRef.current = null;
    }
  }

  function startStallDetection() {
    stopStallDetection();
    lastTimeRef.current = audioRef.current?.currentTime ?? 0;
    lastCheckRef.current = Date.now();

    stallCheckRef.current = window.setInterval(() => {
      const audio = audioRef.current;
      if (!audio || audio.paused) return;

      const now = audio.currentTime;
      const elapsed = Date.now() - lastCheckRef.current;

      if (elapsed > 80 && Math.abs(now - lastTimeRef.current) < 0.01) {
        gapCountRef.current++;
        gapLogRef.current.push({ time: now, durationMs: elapsed });
      }

      lastTimeRef.current = now;
      lastCheckRef.current = Date.now();
    }, 100);
  }

  function stopStallDetection() {
    if (stallCheckRef.current) {
      clearInterval(stallCheckRef.current);
      stallCheckRef.current = 0;
    }
  }

  // --- Track current entry based on playback time ---

  useEffect(() => {
    const es = entriesRef.current;
    if (es.length === 0) {
      setCurrentEntryId(null);
      return;
    }
    let found: string | null = null;
    for (const e of es) {
      if (currentTime >= e.timestamp_start && currentTime < e.timestamp_end) {
        found = e.id;
        break;
      }
    }
    if (!found) {
      for (let i = es.length - 1; i >= 0; i--) {
        if (currentTime >= es[i].timestamp_start) {
          found = es[i].id;
          break;
        }
      }
    }
    setCurrentEntryId(found);
  }, [currentTime]);

  // --- Expose diagnostic API ---

  useEffect(() => {
    window.__audioDebug = {
      isPlaying: () => isPlayingRef.current,
      getGapCount: () => gapCountRef.current,
      getGapLog: () => [...gapLogRef.current],
      getBufferDuration: () => audioRef.current?.duration ?? 0,
      getCurrentTime: () => audioRef.current?.currentTime ?? 0,
      getBuffered: () => {
        const audio = audioRef.current;
        if (!audio) return [];
        const ranges: Array<{ start: number; end: number }> = [];
        for (let i = 0; i < audio.buffered.length; i++) {
          ranges.push({ start: audio.buffered.start(i), end: audio.buffered.end(i) });
        }
        return ranges;
      },
      getReadyState: () => audioRef.current?.readyState ?? 0,
      getNetworkState: () => audioRef.current?.networkState ?? 0,
      resetGaps: () => {
        gapCountRef.current = 0;
        gapLogRef.current = [];
      },
    };
    return () => {
      delete window.__audioDebug;
    };
  }, []);

  // --- Cleanup on unmount ---

  useEffect(() => {
    return () => {
      cleanupAudio();
    };
  }, []);

  // --- actions ---

  const setSource = useCallback((url: string) => {
    const gen = ++generationRef.current;
    cleanupAudio();
    isPlayingRef.current = false;
    setIsPlaying(false);
    setIsLoading(true);
    setCurrentTime(0);
    setDuration(0);
    gapCountRef.current = 0;
    gapLogRef.current = [];

    const audio = new Audio();
    audio.preload = "auto";
    audioRef.current = audio;

    if (url.startsWith("blob:")) {
      blobUrlRef.current = url;
    }

    audio.onloadedmetadata = () => {
      if (gen !== generationRef.current) return;
      setDuration(audio.duration);
      setIsLoading(false);
    };

    audio.ontimeupdate = () => {
      if (gen !== generationRef.current) return;
      setCurrentTime(audio.currentTime);
    };

    audio.onended = () => {
      if (gen !== generationRef.current) return;
      isPlayingRef.current = false;
      setIsPlaying(false);
      setCurrentTime(audio.duration);
      stopStallDetection();
    };

    audio.onerror = () => {
      if (gen !== generationRef.current) return;
      console.error("[AudioPlayer] Audio error:", audio.error?.message);
      setIsLoading(false);
    };

    audio.oncanplaythrough = () => {
      if (gen !== generationRef.current) return;
      setIsLoading(false);
    };

    // Log buffering events for diagnostics
    audio.onwaiting = () => {
      console.warn("[AudioPlayer] Buffering (waiting)...", { time: audio.currentTime });
    };
    audio.onstalled = () => {
      console.warn("[AudioPlayer] Stalled", { time: audio.currentTime });
    };

    audio.src = url;
  }, []);

  const play = useCallback((fromSeconds?: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (fromSeconds !== undefined) {
      audio.currentTime = fromSeconds;
    } else if (audio.duration && audio.currentTime >= audio.duration) {
      audio.currentTime = 0;
    }
    audio.play().then(() => {
      isPlayingRef.current = true;
      setIsPlaying(true);
      startStallDetection();
    }).catch((err) => {
      console.error("[AudioPlayer] Play failed:", err);
    });
  }, []);

  const pause = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    isPlayingRef.current = false;
    setIsPlaying(false);
    setCurrentTime(audio.currentTime);
    stopStallDetection();
  }, []);

  const toggle = useCallback(() => {
    if (isPlayingRef.current) {
      pause();
    } else {
      play();
    }
  }, [play, pause]);

  const seekTo = useCallback((seconds: number) => {
    const audio = audioRef.current;
    if (!audio) return;
    const clamped = Math.max(0, Math.min(seconds, audio.duration || 0));
    audio.currentTime = clamped;
    setCurrentTime(clamped);
  }, []);

  const setPlaybackRate = useCallback((rate: number) => {
    setPlaybackRateState(rate);
    const audio = audioRef.current;
    if (audio) {
      audio.playbackRate = rate;
    }
  }, []);

  const setLoading = useCallback((loading: boolean) => {
    setIsLoading(loading);
  }, []);

  const destroy = useCallback(() => {
    cleanupAudio();
    isPlayingRef.current = false;
    generationRef.current++;
    gapCountRef.current = 0;
    gapLogRef.current = [];
    setCurrentTime(0);
    setDuration(0);
    setIsPlaying(false);
    setIsLoading(false);
    setCurrentEntryId(null);
  }, []);

  return [
    { isPlaying, isLoading, currentTime, duration, playbackRate, currentEntryId },
    { play, pause, toggle, seekTo, setPlaybackRate, setSource, setLoading, destroy },
  ];
}
