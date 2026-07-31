# Dual Loopback Capture Implementation Plan

> **For agentic workers:** REQUIRED: Use subagent-driven-development (if subagents available) or executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture Windows system audio from both the INZONE H3 headset and Anker PowerConf S330 speaker during one Transcriber session without duplicating or compressing the recording timeline.

**Architecture:** Resolve preferred WASAPI loopbacks by stable device-name fragments, open both streams, and route their 100 ms frames through a pure source selector before feeding the existing single loopback buffer. Keep explicit device-index requests single-device, preserve the default-loopback fallback, and rescan preferred endpoints on Windows device events.

**Tech Stack:** Python 3.11, FastAPI, PyAudioWPatch/WASAPI, NumPy, pytest

---

## File Structure

- Create `backend/core/loopback_selector.py`: pure, thread-safe source arbitration with no PyAudio dependency.
- Create `tests/test_loopback_selector.py`: deterministic activity and switching tests.
- Create `tests/test_audio_capture.py`: preferred loopback name matching and fallback-oriented discovery tests.
- Create `tests/test_audio_stream.py`: multi-stream ownership, callback routing, and cleanup tests with fake PyAudio streams.
- Modify `backend/config.py`: preferred loopback name-fragment setting and parsed property.
- Modify `backend/core/audio_capture.py`: preferred loopback selection and discovery.
- Modify `backend/models/audio_stream.py`: multiple loopback streams and callback factories.
- Modify `backend/models/session.py`: automatic multi-loopback startup and event-driven resynchronization.
- Extend `tests/test_session_audio_recording.py`: saved-audio duration and single-track regression coverage.

## Dirty Worktree Safety

The current checkout contains unrelated uncommitted changes, including changes in `backend/config.py` and `backend/models/session.py`. Never stage an entire shared dirty file merely because this plan names it. Before every checkpoint, compare the task diff with the pre-task baseline and stage only proven feature-owned hunks. If ownership cannot be isolated non-interactively, skip that checkpoint commit and leave the verified feature diff uncommitted for the final human-reviewed stage operation. Never revert or overwrite the pre-existing changes.

## Chunk 1: Pure Discovery and Selection

### Task 1: Configure and resolve preferred loopback endpoints

**Files:**
- Modify: `backend/config.py:87-92`
- Modify: `backend/core/audio_capture.py:23-116`
- Create: `tests/test_audio_capture.py`

- [ ] **Step 1: Write failing configuration tests**

Add tests that instantiate `Settings` with an isolated environment and verify:

```python
def test_preferred_loopback_patterns_parse_names(monkeypatch):
    monkeypatch.setenv(
        "LOOPBACK_DEVICE_PATTERNS",
        "INZONE H3, Anker PowerConf S330",
    )
    config = Settings(_env_file=None)
    assert config.preferred_loopback_patterns == (
        "INZONE H3",
        "Anker PowerConf S330",
    )


def test_empty_preferred_loopback_patterns_restore_default_only(monkeypatch):
    monkeypatch.setenv("LOOPBACK_DEVICE_PATTERNS", "")
    config = Settings(_env_file=None)
    assert config.preferred_loopback_patterns == ()
```

- [ ] **Step 2: Run the configuration tests and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_audio_capture.py -v
```

Expected: FAIL because `loopback_device_patterns` and `preferred_loopback_patterns` do not exist.

- [ ] **Step 3: Add the setting and parsed property**

Add to the Audio section of `Settings`:

```python
loopback_device_patterns: str = "INZONE H3,Anker PowerConf S330"

@property
def preferred_loopback_patterns(self) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for part in self.loopback_device_patterns.split(",")
        if part.strip()
    )
```

- [ ] **Step 4: Write failing preferred-device selection tests**

Use constructed `AudioDevice` values to verify that `select_preferred_loopbacks()`:

- matches names case-insensitively;
- includes only `Windows WASAPI` loopbacks;
- preserves configured pattern order;
- returns each device index once;
- returns an empty list for empty patterns.

Representative assertion:

```python
selected = select_preferred_loopbacks(
    devices,
    ("inzone h3", "ANKER POWERCONF S330"),
)
assert [device.index for device in selected] == [25, 29]
```

- [ ] **Step 5: Implement pure selection and runtime discovery**

Add:

```python
def select_preferred_loopbacks(
    devices: list[AudioDevice],
    patterns: tuple[str, ...],
) -> list[AudioDevice]:
    selected: list[AudioDevice] = []
    seen: set[int] = set()
    for pattern in patterns:
        needle = pattern.casefold()
        for device in devices:
            if (
                device.index not in seen
                and device.is_loopback
                and device.host_api == "Windows WASAPI"
                and needle in device.name.casefold()
            ):
                selected.append(device)
                seen.add(device.index)
    return selected


def get_preferred_loopbacks(patterns: tuple[str, ...]) -> list[AudioDevice]:
    return select_preferred_loopbacks(list_audio_devices(), patterns)
```

- [ ] **Step 6: Run tests and checkpoint Chunk 1**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_audio_capture.py -v
```

Expected: PASS.

Commit only if every staged hunk is proven to belong to this task. Otherwise record the passing test result and defer the commit:

```powershell
git add backend/config.py backend/core/audio_capture.py tests/test_audio_capture.py
git commit -m "feat: resolve preferred loopback devices"
```

## Chunk 2: Deterministic Source Arbitration

### Task 2: Select one active loopback without duplicate frames

**Files:**
- Create: `backend/core/loopback_selector.py`
- Create: `tests/test_loopback_selector.py`

- [ ] **Step 1: Write failing selector tests**

Cover these cases using 100 ms NumPy frames and explicit monotonic timestamps:

1. The first source becomes selected.
2. Silent selected-source frames continue to emit.
3. A second active source takes over after the selected source has been silent for `0.2` seconds.
4. A second source does not take over while the selected source remains active.
5. Removing the selected source clears selection.
6. `reset()` clears all source state between sessions.

Representative test:

```python
def test_active_source_switches_after_selected_source_is_silent():
    selector = LoopbackSourceSelector(activity_threshold=0.001, switch_after_s=0.2)
    signal = np.full(1600, 0.1, dtype=np.float32)
    silence = np.zeros(1600, dtype=np.float32)

    assert selector.should_emit(25, signal, now=0.0)
    assert selector.should_emit(25, silence, now=0.1)
    assert selector.should_emit(29, signal, now=0.21)
    assert selector.selected_source == 29
```

- [ ] **Step 2: Run selector tests and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_loopback_selector.py -v
```

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement `LoopbackSourceSelector`**

Use a `threading.Lock` because PyAudio callbacks execute on separate threads. Compute RMS as:

```python
level = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
```

Track:

```python
self._selected_source: int | None
self._last_signal_at: dict[int, float]
self._lock = threading.Lock()
```

`should_emit(source_id, audio, now)` must update signal timestamps, retain the selected source while active, switch only after its last signal is old enough, and return `True` for exactly the source whose callback should feed the shared buffer.

- [ ] **Step 4: Run tests and checkpoint Chunk 2**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_loopback_selector.py -v
```

Expected: PASS.

```powershell
git add backend/core/loopback_selector.py tests/test_loopback_selector.py
git commit -m "feat: arbitrate loopback audio sources"
```

## Chunk 3: Multi-stream Audio Manager

### Task 3: Own two WASAPI loopback streams safely

**Files:**
- Modify: `backend/models/audio_stream.py:17-219`
- Create: `tests/test_audio_stream.py`

- [ ] **Step 1: Write fake-PyAudio ownership tests**

Create fake device info and stream objects. Verify:

- `open_loopback_streams([25, 29])` opens both indices;
- duplicate indices open only once;
- `sync_loopback_streams([29])` closes 25 and retains 29;
- failure opening 29 leaves 25 running;
- `close_streams()` closes mic and every loopback stream;
- `current_loopback_name` joins successful device names;
- `reset_counters()` also resets selector state.

- [ ] **Step 2: Run ownership tests and confirm failure**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_audio_stream.py -v
```

Expected: FAIL because only `_loopback_stream` and `open_loopback_stream()` exist.

- [ ] **Step 3: Replace singleton loopback fields with per-device state**

Introduce focused internal state:

```python
@dataclass
class LoopbackStreamState:
    index: int
    name: str
    sample_rate: int
    channels: int
    stream: object
    callback_count: int = 0
```

Store states in:

```python
self._loopback_streams: dict[int, LoopbackStreamState] = {}
self._loopback_selector = LoopbackSourceSelector()
```

Keep `open_loopback_stream(index)` and `switch_loopback(index)` as compatibility wrappers around the new plural APIs.

- [ ] **Step 4: Add a callback factory**

Build `_make_loopback_callback(device_index)` so each callback looks up its own rate/channels, resamples independently, and calls:

```python
if self._loopback_selector.should_emit(
    device_index,
    audio,
    time.monotonic(),
):
    self._loopback_buffer.feed(audio)
    if self._recorded_loopback is not None:
        self._recorded_loopback.append(audio.copy())
```

Do not append frames from non-selected streams.

- [ ] **Step 5: Implement add/remove synchronization**

`sync_loopback_streams(indices)` must:

1. deduplicate requested indices;
2. close and remove streams no longer requested;
3. open missing streams independently;
4. retain already-open streams;
5. return the successfully open indices;
6. remove closed sources from the selector.

Do not terminate or recreate PyAudio while its streams remain open. Normal default-output changes use `sync_loopback_streams()`. Device add/remove recovery uses the safe all-stream reopen operation specified in Task 4.

- [ ] **Step 6: Run focused tests and checkpoint Chunk 3**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_audio_stream.py tests/test_loopback_selector.py -v
```

Expected: PASS.

```powershell
git add backend/models/audio_stream.py tests/test_audio_stream.py
git commit -m "feat: capture multiple loopback streams"
```

## Chunk 4: Session Startup and Device Recovery

### Task 4: Integrate preferred outputs into local sessions

**Files:**
- Modify: `backend/models/session.py:120-180`
- Modify: `backend/models/session.py:943-1065`
- Extend: `tests/test_session_audio_recording.py`
- Create: `tests/test_session_loopback_devices.py`

- [ ] **Step 1: Write failing automatic-start tests**

Mock model loading, device discovery, and `AudioStreamManager`. Verify:

- automatic local start opens both preferred indices `[25, 29]`;
- no preferred match falls back to the Windows default loopback;
- one preferred match opens only that endpoint;
- explicit `loopback_device_index=25` opens only 25;
- status lists both successful names;
- microphone selection remains the Windows default microphone.

- [ ] **Step 2: Add session-level automatic resolution**

Track whether loopback selection was explicit:

```python
self._automatic_loopback_devices = loopback_device_index is None
```

For automatic local sessions:

```python
preferred = get_preferred_loopbacks(settings.preferred_loopback_patterns)
if not preferred:
    default = get_default_loopback()
    preferred = [default] if default else []
loopback_indices = [device.index for device in preferred]
```

Open the microphone as before, then call `open_loopback_streams(loopback_indices)`. Set `_has_loopback` from the successfully opened stream set, not merely from requested indices.

- [ ] **Step 3: Write failing hot-add/hot-remove tests**

For `_on_device_changed()` and polling fallback, verify:

- adding Anker changes requested indices from `[25]` to `[25, 29]`;
- removing INZONE changes them from `[25, 29]` to `[29]`;
- removing all preferred devices uses the current default loopback when available;
- explicit-index sessions do not get replaced by automatic preferred discovery;
- transitioning from zero to one stream starts the loopback buffer and reconfigures the pipeline;
- transitioning to zero streams sets `_has_loopback=False` and reconfigures the pipeline.
- add/remove refresh closes existing streams before recreating PyAudio, then reopens the current microphone and preferred loopbacks.

- [ ] **Step 4: Extract one resynchronization method**

Avoid duplicating event and polling logic. Add:

```python
async def _sync_automatic_loopback_devices(self) -> None:
    if not self._automatic_loopback_devices:
        return
    devices = get_preferred_loopbacks(settings.preferred_loopback_patterns)
    if not devices:
        default = get_default_loopback()
        devices = [default] if default else []
    loop = asyncio.get_running_loop()
    open_indices = await loop.run_in_executor(
        None,
        self._audio.sync_loopback_streams,
        [device.index for device in devices],
    )
    self._set_loopback_availability(bool(open_indices))
```

Use this method from both `_on_device_changed()` and `_monitor_devices()`. Keep default-microphone switching independent.

For `added` and `removed` events, do not call the current `_recreate_pyaudio()` against open streams. Add an `AudioStreamManager.reopen_devices(mic_index, loopback_indices)` operation that, under `_stream_lock`:

1. closes the microphone and every loopback stream;
2. terminates and recreates the PyAudio instance;
3. opens the freshly resolved microphone index;
4. opens each freshly resolved preferred loopback independently;
5. returns the successfully opened loopback indices.

The event handler must resolve fresh device indices before invoking this operation and update loopback availability from its return value. A short reopen gap is acceptable on physical device add/remove; ordinary headset/speaker playback switching does not use this path because both target streams remain open.

- [ ] **Step 5: Preserve recording duration regression coverage**

Extend the audio-saving tests to prove that only selected-source callback frames reach `_recorded_loopback` and that one second of callbacks produces one second of saved loopback audio, not two seconds.

- [ ] **Step 6: Run session tests and checkpoint Chunk 4**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_session_loopback_devices.py tests/test_session_audio_recording.py tests/test_routes_session_client_id.py -v
```

Expected: PASS.

```powershell
git add backend/models/session.py tests/test_session_loopback_devices.py tests/test_session_audio_recording.py
git commit -m "feat: use preferred loopbacks in sessions"
```

## Chunk 5: Regression and Real-device Verification

### Task 5: Verify the complete recording path

**Files:**
- Modify only files required to repair failures introduced by Tasks 1-4.

- [ ] **Step 1: Run focused backend regression tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests/test_audio_capture.py tests/test_loopback_selector.py tests/test_audio_stream.py tests/test_session_loopback_devices.py tests/test_session_audio_recording.py tests/test_routes_session_client_id.py -v
```

Expected: PASS.

- [ ] **Step 2: Run the full backend suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests -v
```

Expected: PASS with no new warnings or failures.

- [ ] **Step 3: Confirm the running session is idle before deployment**

Run:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/session/status
```

Expected: `status` is `idle`. If it is `running` or `paused`, stop and wait for user approval; do not restart or replace the sidecar.

- [ ] **Step 4: Build and deploy only after explicit approval**

Build the sidecar using the repository command, verify the artifact, then ask for explicit approval before replacing the running application build. Preserve the existing sidecar as a timestamped backup.

- [ ] **Step 5: Perform one real-device session**

During a single test recording:

1. play a spoken test clip through INZONE H3 for at least five seconds;
2. switch Windows playback to Anker PowerConf S330;
3. play a different spoken test clip for at least five seconds;
4. stop normally;
5. confirm both phrases appear in the transcript;
6. inspect `recording.wav` duration and listen around the switch boundary;
7. confirm the status displays both loopback names while connected.

Expected: both sections are transcribed and recorded once, with no doubled duration and no session restart.

- [ ] **Step 6: Review final diff and commit repairs**

Run:

```powershell
git diff --check
git status --short
```

Stage and commit only files belonging to this feature. Do not stage or revert unrelated dirty-worktree changes.
