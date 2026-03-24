import { test, expect } from "@playwright/test";

// Tauri API モック — Vite dev server 単体で動かすために __TAURI_INTERNALS__ をスタブ化
const TAURI_MOCK_SCRIPT = `
  if (!window.__TAURI_INTERNALS__) {
    window.__TAURI_INTERNALS__ = {
      metadata: {
        currentWindow: { label: 'main' },
        currentWebview: { label: 'main' },
      },
      invoke: (cmd, args) => {
        return new Promise((_, reject) => reject(new Error('Tauri mock: ' + cmd)));
      },
      transformCallback: (cb) => {
        const id = Math.random();
        window['_' + id] = cb;
        return id;
      },
      convertFileSrc: (path) => path,
    };
  }
`;

test.describe("Audio Player (Web Audio API)", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(TAURI_MOCK_SCRIPT);
  });

  test("Web Audio API is available in browser context", async ({ page }) => {
    await page.goto("/");
    const hasWebAudio = await page.evaluate(() => {
      return (
        typeof AudioContext !== "undefined" &&
        typeof AudioContext.prototype.decodeAudioData === "function"
      );
    });
    expect(hasWebAudio).toBe(true);
  });

  test("decodeAudioData can decode a PCM_16 WAV buffer", async ({ page }) => {
    await page.goto("/");
    const result = await page.evaluate(async () => {
      // Generate a valid 1-second PCM_16 WAV (16kHz mono)
      const sampleRate = 16000;
      const numChannels = 1;
      const bitsPerSample = 16;
      const numSamples = sampleRate; // 1 second
      const dataSize = numSamples * numChannels * (bitsPerSample / 8);
      const headerSize = 44;
      const buffer = new ArrayBuffer(headerSize + dataSize);
      const view = new DataView(buffer);

      const writeStr = (offset: number, str: string) => {
        for (let i = 0; i < str.length; i++)
          view.setUint8(offset + i, str.charCodeAt(i));
      };

      // RIFF header
      writeStr(0, "RIFF");
      view.setUint32(4, 36 + dataSize, true);
      writeStr(8, "WAVE");
      // fmt chunk
      writeStr(12, "fmt ");
      view.setUint32(16, 16, true); // chunk size
      view.setUint16(20, 1, true); // PCM format
      view.setUint16(22, numChannels, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * numChannels * (bitsPerSample / 8), true);
      view.setUint16(32, numChannels * (bitsPerSample / 8), true);
      view.setUint16(34, bitsPerSample, true);
      // data chunk
      writeStr(36, "data");
      view.setUint32(40, dataSize, true);

      // Fill with a 440Hz sine wave
      for (let i = 0; i < numSamples; i++) {
        const sample = Math.sin((2 * Math.PI * 440 * i) / sampleRate);
        view.setInt16(headerSize + i * 2, sample * 32767, true);
      }

      const ctx = new AudioContext();
      const audioBuffer = await ctx.decodeAudioData(buffer);
      const result = {
        duration: audioBuffer.duration,
        channels: audioBuffer.numberOfChannels,
        sampleRate: audioBuffer.sampleRate,
      };
      await ctx.close();
      return result;
    });

    expect(result.duration).toBeGreaterThan(0.9);
    expect(result.duration).toBeLessThan(1.1);
    expect(result.channels).toBe(1);
  });

  test("AudioBufferSourceNode plays without errors", async ({ page }) => {
    await page.goto("/");
    const result = await page.evaluate(async () => {
      // Create a short (0.1s) silent buffer and play it
      const ctx = new AudioContext();
      const buf = ctx.createBuffer(1, 4410, 44100); // 0.1s
      const source = ctx.createBufferSource();
      source.buffer = buf;
      source.connect(ctx.destination);

      return new Promise<{ played: boolean; error: string | null }>((resolve) => {
        source.onended = () => {
          ctx.close();
          resolve({ played: true, error: null });
        };
        try {
          source.start(0);
        } catch (err: unknown) {
          ctx.close();
          resolve({ played: false, error: String(err) });
        }
      });
    });

    expect(result.played).toBe(true);
    expect(result.error).toBeNull();
  });

  test("playbackRate changes are applied correctly", async ({ page }) => {
    await page.goto("/");
    const result = await page.evaluate(async () => {
      const ctx = new AudioContext();
      const buf = ctx.createBuffer(1, 44100, 44100); // 1s buffer
      const source = ctx.createBufferSource();
      source.buffer = buf;
      source.connect(ctx.destination);
      source.playbackRate.value = 2.0;

      const rateApplied = source.playbackRate.value;
      source.start(0);
      source.stop();
      source.disconnect();
      await ctx.close();
      return { rateApplied };
    });

    expect(result.rateApplied).toBe(2.0);
  });
});

// --- WAV generator helper ---
function generateWavBuffer(
  durationSeconds: number,
  sampleRate: number,
  channels: number,
): ArrayBuffer {
  const bitsPerSample = 16;
  const numSamples = sampleRate * durationSeconds;
  const dataSize = numSamples * channels * (bitsPerSample / 8);
  const headerSize = 44;
  const buffer = new ArrayBuffer(headerSize + dataSize);
  const view = new DataView(buffer);

  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++)
      view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * channels * (bitsPerSample / 8), true);
  view.setUint16(32, channels * (bitsPerSample / 8), true);
  view.setUint16(34, bitsPerSample, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  for (let i = 0; i < numSamples; i++) {
    const sample = Math.sin((2 * Math.PI * 440 * i) / sampleRate);
    const val = Math.max(-32768, Math.min(32767, sample * 32767));
    for (let ch = 0; ch < channels; ch++) {
      view.setInt16(headerSize + (i * channels + ch) * 2, val, true);
    }
  }

  return buffer;
}

// Setup audio pipeline with AnalyserNode + gap detection inside browser context
// Returns serialisable info; exposes __testPlay / __testPause / __testCleanup on window
async function setupAudioPipeline(
  page: import("@playwright/test").Page,
  durationSeconds: number,
  sampleRate: number,
  channels: number,
) {
  // Transfer WAV as base64 because page.evaluate can't send ArrayBuffer directly
  const wavBuffer = generateWavBuffer(durationSeconds, sampleRate, channels);
  const bytes = new Uint8Array(wavBuffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  const base64 = Buffer.from(binary, "binary").toString("base64");

  return page.evaluate(async (b64: string) => {
    // Decode base64 to ArrayBuffer
    const binStr = atob(b64);
    const len = binStr.length;
    const arr = new Uint8Array(len);
    for (let i = 0; i < len; i++) arr[i] = binStr.charCodeAt(i);
    const wavArrayBuffer = arr.buffer;

    const ctx = new AudioContext();
    const audioBuffer = await ctx.decodeAudioData(wavArrayBuffer);

    const analyser = ctx.createAnalyser();
    analyser.fftSize = 2048;
    analyser.smoothingTimeConstant = 0.3;

    let gapCount = 0;
    const gapLog: Array<{ time: number; durationMs: number }> = [];
    let consecutiveSilence = 0;
    let playing = false;
    let gapInterval = 0;
    let sourceNode: AudioBufferSourceNode | null = null;
    let playStartCtxTime = 0;
    let playStartOffset = 0;

    function getRMS(): number {
      const data = new Float32Array(analyser.fftSize);
      analyser.getFloatTimeDomainData(data);
      let sum = 0;
      for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
      return Math.sqrt(sum / data.length);
    }

    (window as any).__audioDebug = {
      getRMS,
      getWaveform: () => {
        const data = new Float32Array(analyser.fftSize);
        analyser.getFloatTimeDomainData(data);
        return data;
      },
      isPlaying: () => playing,
      getGapCount: () => gapCount,
      getGapLog: () => [...gapLog],
      getSampleRate: () => ctx.sampleRate,
      getBufferDuration: () => audioBuffer.duration,
      resetGaps: () => { gapCount = 0; gapLog.length = 0; consecutiveSilence = 0; },
    };

    (window as any).__testPlay = (offset = 0) => {
      if (sourceNode) {
        try { sourceNode.stop(); sourceNode.disconnect(); } catch { /* noop */ }
      }
      const src = ctx.createBufferSource();
      src.buffer = audioBuffer;
      src.connect(analyser);
      analyser.connect(ctx.destination);
      src.start(0, offset);
      sourceNode = src;
      playing = true;
      playStartCtxTime = ctx.currentTime;
      playStartOffset = offset;

      clearInterval(gapInterval);
      consecutiveSilence = 0;
      gapInterval = window.setInterval(() => {
        if (!playing) return;
        const rms = getRMS();
        if (rms < 0.001) {
          consecutiveSilence++;
          if (consecutiveSilence === 2) {
            gapCount++;
            const elapsed = (ctx.currentTime - playStartCtxTime) + playStartOffset;
            gapLog.push({ time: elapsed, durationMs: 100 });
          } else if (consecutiveSilence > 2) {
            const last = gapLog[gapLog.length - 1];
            if (last) last.durationMs += 50;
          }
        } else {
          consecutiveSilence = 0;
        }
      }, 50);

      src.onended = () => {
        playing = false;
        clearInterval(gapInterval);
      };
    };

    (window as any).__testPause = () => {
      if (sourceNode) {
        try { sourceNode.stop(); sourceNode.disconnect(); } catch { /* noop */ }
        sourceNode = null;
      }
      playing = false;
      clearInterval(gapInterval);
    };

    (window as any).__testGetElapsed = () => {
      if (!playing) return -1;
      return ctx.currentTime - playStartCtxTime;
    };

    (window as any).__testCleanup = async () => {
      if (sourceNode) {
        try { sourceNode.stop(); sourceNode.disconnect(); } catch { /* noop */ }
      }
      clearInterval(gapInterval);
      analyser.disconnect();
      await ctx.close();
      delete (window as any).__audioDebug;
      delete (window as any).__testPlay;
      delete (window as any).__testPause;
      delete (window as any).__testGetElapsed;
      delete (window as any).__testCleanup;
    };

    return {
      duration: audioBuffer.duration,
      sampleRate: ctx.sampleRate,
      channels: audioBuffer.numberOfChannels,
    };
  }, base64);
}

// --- HTMLAudioElement + BlobURL playback tests (new architecture) ---
test.describe("HTMLAudioElement Blob URL Playback", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(TAURI_MOCK_SCRIPT);
    await page.goto("/");
  });

  test("HTMLAudioElement plays from Blob URL without errors", async ({ page }) => {
    const wavBuffer = generateWavBuffer(3, 44100, 1);
    const bytes = new Uint8Array(wavBuffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const base64 = Buffer.from(binary, "binary").toString("base64");

    const result = await page.evaluate(async (b64: string) => {
      const binStr = atob(b64);
      const arr = new Uint8Array(binStr.length);
      for (let i = 0; i < binStr.length; i++) arr[i] = binStr.charCodeAt(i);
      const blob = new Blob([arr.buffer], { type: "audio/wav" });
      const blobUrl = URL.createObjectURL(blob);

      const audio = new Audio();
      audio.src = blobUrl;

      return new Promise<{ played: boolean; duration: number; error: string | null }>((resolve) => {
        audio.onloadedmetadata = () => {
          audio.play().then(() => {
            setTimeout(() => {
              const dur = audio.duration;
              audio.pause();
              URL.revokeObjectURL(blobUrl);
              resolve({ played: true, duration: dur, error: null });
            }, 500);
          }).catch((err) => {
            URL.revokeObjectURL(blobUrl);
            resolve({ played: false, duration: 0, error: String(err) });
          });
        };
        audio.onerror = () => {
          URL.revokeObjectURL(blobUrl);
          resolve({ played: false, duration: 0, error: audio.error?.message ?? "unknown error" });
        };
      });
    }, base64);

    expect(result.played).toBe(true);
    expect(result.error).toBeNull();
    expect(result.duration).toBeGreaterThan(2.5);
  });

  test("MediaElementSourceNode routes audio through AnalyserNode", async ({ page }) => {
    const wavBuffer = generateWavBuffer(3, 44100, 1);
    const bytes = new Uint8Array(wavBuffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const base64 = Buffer.from(binary, "binary").toString("base64");

    const result = await page.evaluate(async (b64: string) => {
      const binStr = atob(b64);
      const arr = new Uint8Array(binStr.length);
      for (let i = 0; i < binStr.length; i++) arr[i] = binStr.charCodeAt(i);
      const blob = new Blob([arr.buffer], { type: "audio/wav" });
      const blobUrl = URL.createObjectURL(blob);

      const audio = new Audio();
      audio.src = blobUrl;

      const ctx = new AudioContext();
      const source = ctx.createMediaElementSource(audio);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 2048;
      source.connect(analyser);
      analyser.connect(ctx.destination);

      await new Promise<void>((resolve) => {
        audio.oncanplaythrough = () => resolve();
        audio.load();
      });

      await audio.play();
      await new Promise(r => setTimeout(r, 500));

      const data = new Float32Array(analyser.fftSize);
      analyser.getFloatTimeDomainData(data);
      let sumSq = 0;
      for (let i = 0; i < data.length; i++) sumSq += data[i] * data[i];
      const rms = Math.sqrt(sumSq / data.length);

      audio.pause();
      source.disconnect();
      analyser.disconnect();
      await ctx.close();
      URL.revokeObjectURL(blobUrl);

      return { rms, connected: true };
    }, base64);

    expect(result.connected).toBe(true);
    expect(result.rms).toBeGreaterThan(0.01);
  });

  test("HTMLAudioElement playback has no stalls (timeupdate monitoring)", async ({ page }) => {
    const wavBuffer = generateWavBuffer(5, 44100, 1);
    const bytes = new Uint8Array(wavBuffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
    const base64 = Buffer.from(binary, "binary").toString("base64");

    const result = await page.evaluate(async (b64: string) => {
      const binStr = atob(b64);
      const arr = new Uint8Array(binStr.length);
      for (let i = 0; i < binStr.length; i++) arr[i] = binStr.charCodeAt(i);
      const blob = new Blob([arr.buffer], { type: "audio/wav" });
      const blobUrl = URL.createObjectURL(blob);

      const audio = new Audio();
      audio.src = blobUrl;

      await new Promise<void>((resolve) => {
        audio.oncanplaythrough = () => resolve();
        audio.load();
      });

      let stallCount = 0;
      let lastTime = 0;
      let lastCheck = Date.now();
      const stallLog: Array<{ time: number; elapsed: number }> = [];

      const checker = setInterval(() => {
        const now = audio.currentTime;
        const elapsed = Date.now() - lastCheck;
        if (elapsed > 80 && !audio.paused && Math.abs(now - lastTime) < 0.01) {
          stallCount++;
          stallLog.push({ time: now, elapsed });
        }
        lastTime = now;
        lastCheck = Date.now();
      }, 100);

      await audio.play();
      await new Promise(r => setTimeout(r, 3000));
      audio.pause();
      clearInterval(checker);
      URL.revokeObjectURL(blobUrl);

      return { stallCount, stallLog, currentTime: audio.currentTime };
    }, base64);

    expect(result.stallCount).toBe(0);
    expect(result.currentTime).toBeGreaterThan(2.5);
  });
});

// --- AnalyserNode diagnostic tests ---
test.describe("Audio Diagnostics (AnalyserNode)", () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(TAURI_MOCK_SCRIPT);
    await page.goto("/");
  });

  test("RMS is non-zero during 440Hz playback", async ({ page }) => {
    await setupAudioPipeline(page, 3, 44100, 1);
    await page.evaluate(() => (window as any).__testPlay(0));
    await page.waitForTimeout(300);

    const rmsValues = await page.evaluate(async () => {
      const values: number[] = [];
      for (let i = 0; i < 5; i++) {
        values.push((window as any).__audioDebug.getRMS());
        await new Promise(r => setTimeout(r, 100));
      }
      return values;
    });

    for (const rms of rmsValues) {
      expect(rms).toBeGreaterThan(0.01);
    }

    await page.evaluate(() => (window as any).__testCleanup());
  });

  test("no gaps detected during continuous playback", async ({ page }) => {
    await setupAudioPipeline(page, 3, 44100, 1);

    await page.evaluate(() => {
      (window as any).__audioDebug.resetGaps();
      (window as any).__testPlay(0);
    });
    await page.waitForTimeout(2000);

    const gapCount = await page.evaluate(() => (window as any).__audioDebug.getGapCount());
    const gapLog = await page.evaluate(() => (window as any).__audioDebug.getGapLog());

    expect(gapCount).toBe(0);
    expect(gapLog).toHaveLength(0);

    await page.evaluate(() => (window as any).__testCleanup());
  });

  test("waveform data has actual amplitude during playback", async ({ page }) => {
    await setupAudioPipeline(page, 2, 44100, 1);
    await page.evaluate(() => (window as any).__testPlay(0));
    await page.waitForTimeout(300);

    const stats = await page.evaluate(() => {
      const waveform = (window as any).__audioDebug.getWaveform() as Float32Array;
      let min = Infinity, max = -Infinity;
      for (let i = 0; i < waveform.length; i++) {
        if (waveform[i] < min) min = waveform[i];
        if (waveform[i] > max) max = waveform[i];
      }
      return { length: waveform.length, min, max, range: max - min };
    });

    expect(stats.length).toBe(2048);
    expect(stats.range).toBeGreaterThan(0.1);

    await page.evaluate(() => (window as any).__testCleanup());
  });

  test("seek plays from correct offset", async ({ page }) => {
    await setupAudioPipeline(page, 5, 44100, 1);
    await page.evaluate(() => (window as any).__testPlay(2.0));
    await page.waitForTimeout(500);

    const elapsed = await page.evaluate(() => (window as any).__testGetElapsed());
    expect(elapsed).toBeGreaterThan(0.3);
    expect(elapsed).toBeLessThan(1.5);

    const rms = await page.evaluate(() => (window as any).__audioDebug.getRMS());
    expect(rms).toBeGreaterThan(0.01);

    await page.evaluate(() => (window as any).__testCleanup());
  });

  test("pause stops audio output", async ({ page }) => {
    await setupAudioPipeline(page, 3, 44100, 1);
    await page.evaluate(() => (window as any).__testPlay(0));
    await page.waitForTimeout(300);

    const rmsPlaying = await page.evaluate(() => (window as any).__audioDebug.getRMS());
    expect(rmsPlaying).toBeGreaterThan(0.01);

    await page.evaluate(() => (window as any).__testPause());
    await page.waitForTimeout(200);

    const isPlaying = await page.evaluate(() => (window as any).__audioDebug.isPlaying());
    expect(isPlaying).toBe(false);

    const rmsPaused = await page.evaluate(() => (window as any).__audioDebug.getRMS());
    expect(rmsPaused).toBeLessThan(0.01);

    await page.evaluate(() => (window as any).__testCleanup());
  });

  test("5-second stereo WAV plays without gaps", async ({ page }) => {
    const info = await setupAudioPipeline(page, 5, 44100, 2);

    expect(info.duration).toBeGreaterThan(4.5);
    expect(info.duration).toBeLessThan(5.5);

    await page.evaluate(() => {
      (window as any).__audioDebug.resetGaps();
      (window as any).__testPlay(0);
    });
    await page.waitForTimeout(3000);

    const gapCount = await page.evaluate(() => (window as any).__audioDebug.getGapCount());
    expect(gapCount).toBe(0);

    const rms = await page.evaluate(() => (window as any).__audioDebug.getRMS());
    expect(rms).toBeGreaterThan(0.01);

    await page.evaluate(() => (window as any).__testCleanup());
  });
});
