// --- Session ---

export type SessionStatus = "idle" | "starting" | "running" | "paused" | "stopping";

export interface SessionInfo {
  status: SessionStatus;
  session_id: string;
  started_at: string | null;
  segment_count: number;
  entry_count: number;
  elapsed_seconds: number;
  mic_device?: string;
  loopback_device?: string;
}

export interface StartRequest {
  device_index?: number | null;
  loopback_device_index?: number | null;
  session_name?: string;
}

// --- Transcript Entry ---

export interface TranscriptEntry {
  id: string;
  text: string;
  raw_text: string;
  speaker_name: string;
  speaker_id: string;
  speaker_confidence: number;
  cluster_id?: string | null;
  suggested_speaker_id?: string | null;
  suggested_speaker_name?: string | null;
  timestamp_start: number;
  timestamp_end: number;
  created_at?: string;
  bookmarked?: boolean;
  refined?: boolean;
}

// --- Speaker ---

export interface Speaker {
  id: string;
  name: string;
  sample_count: number;
  has_embedding: boolean;
  created_at?: string;
}

// --- Dictionary ---
// Backend stores rules with "from"/"to" keys (not from_text/to_text)
// But POST/PUT requests use from_text/to_text (Pydantic field names)

export interface ReplacementRule {
  from: string;
  to: string;
  case_sensitive: boolean;
  enabled: boolean;
  is_regex: boolean;
  note: string;
  auto_learned?: boolean;
  confidence?: number;
  occurrence_count?: number;
}

export interface ReplacementRuleRequest {
  from_text: string;
  to_text: string;
  case_sensitive: boolean;
  enabled: boolean;
  is_regex: boolean;
  note: string;
}

export interface DictionaryConfig {
  version: number;
  replacements: ReplacementRule[];
  fillers: string[];
  filler_removal_enabled: boolean;
}

export interface FillerConfigRequest {
  fillers?: string[] | null;
  filler_removal_enabled?: boolean | null;
}

// --- Model ---

export interface ModelInfo {
  name: string;
  vram_mb: number;
}

export interface ModelStatus {
  current_model: string;
  is_loaded: boolean;
  available_models: ModelInfo[];
}

export interface ModelSwitchRequest {
  model_size: string;
}

export interface ModelLoadingStatus {
  stage: string; // "" | "unloading" | "warming" | "loading" | "ready"
  progress: number; // 0.0 - 1.0
}

// --- Audio ---

export interface AudioDevice {
  index: number;
  name: string;
  host_api: string;
  max_input_channels: number;
  default_sample_rate: number;
  is_loopback: boolean;
}

export interface AudioDevicesResponse {
  devices: AudioDevice[];
  default_mic_index: number | null;
  default_loopback_index: number | null;
  default_microphone: AudioDevice | null;
  default_loopback: AudioDevice | null;
}

// --- GPU ---

export interface GpuStatus {
  available: boolean;
  name?: string;
  temperature_c?: number;
  gpu_utilization_pct?: number;
  vram_total_mb?: number;
  vram_used_mb?: number;
  vram_free_mb?: number;
  error?: string;
}

// --- Summary ---

export interface SummaryUsage {
  total_tokens?: number;
  cost_usd?: number;
}

export interface SummaryResult {
  session_id: string;
  summary: string;
  title?: string;
  usage?: SummaryUsage;
  cached?: boolean;  // キャッシュヒットを示す
}

export interface GeminiModelInfo {
  id: string;
  label: string;
  input_price: number;
  output_price: number;
  speed: "very_fast" | "fast" | "slow";
  accuracy: "low" | "medium" | "high" | "very_high";
}

export interface GeminiModelsResponse {
  current_model: string;
  models: GeminiModelInfo[];
}

// --- Transcript Sessions ---

export interface TranscriptSession {
  session_id: string;
  session_name?: string;
  started_at?: string;
  saved_at?: string;
  entry_count?: number;
  screenshot_count?: number;
  total_size_bytes?: number;
  is_favorite?: boolean;
  folder?: string;
}

// --- Entry Edit ---

export interface EntryEditRequest {
  text?: string;
  speaker_name?: string;
  speaker_id?: string;
}

export interface EntryEditResponse {
  entry: TranscriptEntry;
}

// --- Correction Learning ---

export interface CorrectionRecord {
  original: string;
  corrected: string;
  field: string;
  session_id: string;
  entry_id: string;
  timestamp: string;
}

export interface LearningSuggestion {
  from_text: string;
  to_text: string;
  count: number;
  confidence: number;
  examples: { session_id: string; timestamp: string }[];
}

// --- WebSocket Messages ---

export interface WsEntryMessage {
  type: "entry";
  data: TranscriptEntry;
}

export interface WsStatusMessage {
  type: "status";
  data: SessionInfo;
}

export interface WsPongMessage {
  type: "pong";
}

export interface WsClearMessage {
  type: "clear";
}

export interface WsRefreshMessage {
  type: "refresh";
}

export interface WsUpdateMessage {
  type: "update";
  data: Array<{ id: string; text: string; refined: boolean }>;
}

export type WsMessage = WsEntryMessage | WsStatusMessage | WsPongMessage | WsClearMessage | WsRefreshMessage | WsUpdateMessage;

// --- Register Speaker from Entry ---

export interface RegisterSpeakerRequest {
  entry_index: number;
  name: string;
}

export interface RegisterSpeakerResponse {
  speaker: Speaker;
  entry_index: number;
  entries: TranscriptEntry[];
}

// --- Name Cluster ---

export interface NameClusterRequest {
  cluster_id: string;
  name: string;
  is_guest?: boolean;
}

export interface NameClusterResponse {
  speaker: Speaker;
  updated_entry_ids: string[];
  entries: TranscriptEntry[];
}

// --- Expected Speakers ---

export interface ExpectedSpeakersRequest {
  names: string[];
  speaker_ids?: string[];
}

export interface ExpectedSpeakersResponse {
  expected_speakers: string[];
}

// --- Screenshots ---

export interface ScreenshotInfo {
  filename: string;
  relative_seconds: number;
  size_bytes: number;
}

export interface ScreenshotsResponse {
  session_id: string;
  screenshots: ScreenshotInfo[];
}

export interface ScreenCaptureConfig {
  screenshot_enabled: boolean;
  screenshot_interval: number;
  screenshot_quality: number;
}

export interface MeetingConfig {
  call_notification_enabled: boolean;
  screenshot_enabled: boolean;
  audio_saving_enabled: boolean;
}
