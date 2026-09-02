# Shared Model Runtime Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Share heavyweight speech-recognition and speaker-model weights across all backend clients while preserving independent meeting state and serializing access to each shared inference engine.

**Architecture:** Add one process-wide `ModelRuntime` that owns the shared `Transcriber`, speaker embedding model, and segmentation model. Each `TranscriptionSession` keeps its own audio buffers, entries, clustering state, adaptive speaker threshold, segmentation cursor, and refinement tasks, but receives lightweight diarizer/refiner facades backed by the shared model objects. Model switching is process-wide and is rejected while any session is active.

**Tech Stack:** Python 3.11, asyncio, threading locks, FastAPI, PyTorch, whisper.cpp, pytest

---

## Chunk 1: Shared model boundaries

### Task 1: Specify shared and session-local ownership

**Files:**
- Create: `backend/core/model_runtime.py`
- Modify: `backend/core/diarizer.py`
- Modify: `backend/core/segmentation_refiner.py`
- Test: `tests/test_model_runtime.py`

- [ ] **Step 1: Write failing ownership tests**

  Assert that two sessions share the same `Transcriber`, speaker model backend, and segmentation model backend while retaining distinct `Diarizer`, adaptive threshold tracker, `SegmentationRefiner`, and processing cursor objects.

- [ ] **Step 2: Run the ownership tests and verify failure**

  Run: `.venv\Scripts\python.exe -m pytest tests/test_model_runtime.py -q`

  Expected: FAIL because `ModelRuntime` and injectable model backends do not exist.

- [ ] **Step 3: Extract heavyweight model holders**

  Add:

  ```python
  class SpeakerEmbeddingModel:
      def load_model(self) -> None: ...
      def unload_model(self) -> None: ...
      def extract_embedding(self, audio, sample_rate=16000): ...

  class SegmentationModel:
      def load_model(self) -> None: ...
      def unload_model(self) -> None: ...
      def run_chunk(self, audio, sample_rate=16000): ...
  ```

  Each holder owns a load lock and an inference lock. `Diarizer` and `SegmentationRefiner` accept these holders through their constructors and retain session-local adaptive state.

- [ ] **Step 4: Add the process-wide runtime**

  ```python
  class ModelRuntime:
      transcriber: Transcriber
      speaker_model: SpeakerEmbeddingModel
      segmentation_model: SegmentationModel

      def create_diarizer(self) -> Diarizer: ...
      def create_segmentation_refiner(self) -> SegmentationRefiner: ...

  def get_model_runtime() -> ModelRuntime: ...
  ```

- [ ] **Step 5: Run ownership tests**

  Expected: PASS.

## Chunk 2: Session integration and serialized inference

### Task 2: Inject the runtime into every transcription session

**Files:**
- Modify: `backend/models/session.py`
- Modify: `backend/core/transcriber.py`
- Test: `tests/test_model_runtime.py`
- Test: `tests/test_transcriber_runtime.py`

- [ ] **Step 1: Write failing registry and serialization tests**

  Verify that the default session and remote client sessions use the same runtime. Run two concurrent ASR calls against a blocking fake model and assert that maximum concurrent model calls is one.

- [ ] **Step 2: Run tests and verify failure**

  Expected: sessions own different model objects and ASR calls overlap.

- [ ] **Step 3: Add runtime injection**

  Give `TranscriptionSession.__init__` an optional `model_runtime` argument. Default it to `get_model_runtime()`, assign the shared transcriber, and create session-local diarizer/refiner facades from the runtime.

- [ ] **Step 4: Serialize ASR inference**

  Add a dedicated inference lock to `Transcriber` and hold it around the underlying faster-whisper or whisper.cpp transcription call. Keep model loading and inference locks separate.

- [ ] **Step 5: Run focused tests**

  Expected: shared ownership and serialization tests PASS.

## Chunk 3: Global model lifecycle

### Task 3: Make preload and model switching process-wide

**Files:**
- Modify: `backend/main.py`
- Modify: `backend/api/routes_session.py`
- Modify: `backend/api/routes_speaker.py`
- Modify: `backend/api/ws_audio_ingest.py`
- Test: `tests/test_routes_session_client_id.py`
- Test: `tests/test_ws_audio_ingest.py`
- Test: `tests/test_model_runtime.py`

- [ ] **Step 1: Write failing lifecycle tests**

  Verify that model preload loads each heavyweight model once even when multiple sessions start, speaker-management endpoints use the shared speaker model, and a model switch returns HTTP 409 while any session is active.

- [ ] **Step 2: Run tests and verify failure**

- [ ] **Step 3: Route lifecycle operations through `ModelRuntime`**

  Preload the runtime once at application startup. Keep existing session start APIs, but let their model-load calls delegate idempotently to the shared holders. Use the shared runtime in speaker endpoints.

- [ ] **Step 4: Protect global model switching**

  Reject model switching when `active_session_count() > 0`. Keep warm-cache and loading-status endpoints tied to the shared transcriber.

- [ ] **Step 5: Run lifecycle tests**

  Expected: PASS.

## Chunk 4: Regression and packaged runtime verification

### Task 4: Verify behavior, memory ownership, and packaging

**Files:**
- Modify only if tests reveal a regression.

- [ ] **Step 1: Run all backend tests**

  Run: `.venv\Scripts\python.exe -m pytest -q`

  Expected: all tests PASS; only the existing `pynvml` dependency warning may remain.

- [ ] **Step 2: Run frontend tests**

  Run: `cd tauri-app && npx tsc --noEmit && npx playwright test`

  Expected: typecheck and all E2E tests PASS.

- [ ] **Step 3: Build the backend without changing dependencies**

  Run: `.venv\Scripts\python.exe -m PyInstaller --noconfirm transcriber-backend.spec`

- [ ] **Step 4: Build and deploy the Tauri application while idle**

  Confirm `/api/session/status` is `idle`, replace the generated frontend and sidecar artifacts, and restart the app.

- [ ] **Step 5: Verify packaged behavior**

  Confirm `/api/health`, `/api/speakers`, one child `whisper-server`, and session status. Inspect process memory and verify additional idle client sessions do not create additional heavyweight models.

## Non-goals

- Do not share audio buffers, transcript entries, clustering state, adaptive thresholds, or refinement cursors.
- Do not change API payloads or the configured maximum concurrent session count.
- Do not add dependencies, change the Tauri application identifier, commit, or push.
