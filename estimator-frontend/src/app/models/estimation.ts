export type ProjectType = 'mobile_app' | 'web_saas' | 'internal_tool' | 'data_pipeline';
export type DetailLevel = 'summary' | 'medium' | 'detailed';
export type OutputFormat = 'phases_table' | 'line_items' | 'narrative';
export type EstimationStatus = 'editing' | 'running' | 'finished' | 'error';

export interface Phase {
  name: string;
  duration_weeks: number;
  cost_eur: number;
  summary: string;
}

export interface EstimationResult {
  summary: string;
  confidence_pct: number;
  phases: Phase[];
  total_duration_weeks: number;
  total_cost_eur: number;
}

/** Lightweight row for the landing list. */
export interface EstimationListItem {
  id: string;
  title: string;
  status: EstimationStatus;
  created_at: string;
  updated_at: string;
}

/** Full persisted record for the detail view. */
export interface EstimationRecord {
  id: string;
  title: string;
  status: EstimationStatus;
  /** Set when this record mirrors a conversational session (enables the thread view). */
  session_id: string | null;
  description: string;
  project_type: ProjectType;
  detail_level: DetailLevel;
  output_format: OutputFormat;
  result: EstimationResult | null;
  prompt_version: string | null;
  cached: boolean | null;
  model: string | null;
  provider: string | null;
  latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cost_usd: number | null;
  finish_reason: string | null;
  error_reason: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

/** Per-call LLM telemetry (null on a cache hit). */
export interface LlmUsage {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number | null;
  finish_reason: string | null;
}

/** Raw response of the stateless + conversational estimate endpoints. */
export interface EstimationResponse {
  result: EstimationResult;
  prompt_version: string;
  cached: boolean;
  usage: LlmUsage | null;
  /** Present only on the Actor-Critic-Boss endpoint (/estimate-acb). */
  acb?: BossTrace | null;
}

/** Audience tier for the v3 prompt + Critic (Session 5 live). */
export type AcbTier = 'executive' | 'pm' | 'developer' | 'default';

/** The Boss's decision after a single actor+critic round. */
export type BossDecision = 'accept' | 'iterate' | 'synthesize';

/** Audit record for one actor+critic iteration of the Boss loop. */
export interface ACBIteration {
  iteration: number;
  decision_after: BossDecision;
  critic_verdict: string;
  critic_confidence: number;
  issue_summary: string[];
}

/** Full Actor-Critic-Boss audit trail attached to an ACB response. */
export interface BossTrace {
  iterations: ACBIteration[];
  final_decision: BossDecision;
  iterations_run: number;
}

/** Session 5 — the durable facts kept across turns (lives apart from history). */
export interface ProjectMetadata {
  project_name: string | null;
  assumed_team_size: number | null;
  mentioned_technologies: string[];
  agreed_scope: string | null;
}

/** GET /sessions/{id} debug view. */
export interface SessionInfo {
  session_id: string;
  message_count: number;
  max_turns: number;
  metadata: ProjectMetadata;
}

/** Local view-model for one rendered turn in the conversation thread. */
export interface ConversationTurn {
  transcript: string;
  attachments: string[];
  response: EstimationResponse;
}

/** One persisted message of a session's history (GET /sessions/{id}/conversation). */
export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** Full turn-by-turn history of a session. */
export interface Conversation {
  session_id: string;
  max_turns: number;
  metadata: ProjectMetadata;
  messages: ConversationMessage[];
}

export interface EstimationCreate {
  title: string;
  description?: string;
  project_type?: ProjectType;
  detail_level?: DetailLevel;
  output_format?: OutputFormat;
}

export interface EstimationUpdate {
  title?: string;
  description?: string;
  project_type?: ProjectType;
  detail_level?: DetailLevel;
  output_format?: OutputFormat;
}

export interface ProjectTypeOption {
  value: ProjectType;
  label: string;
}
export interface DetailLevelOption {
  value: DetailLevel;
  label: string;
}
export interface OutputFormatOption {
  value: OutputFormat;
  label: string;
}

export const PROJECT_TYPES: ProjectTypeOption[] = [
  { value: 'mobile_app', label: 'Aplicación móvil' },
  { value: 'web_saas', label: 'Web SaaS' },
  { value: 'internal_tool', label: 'Herramienta interna' },
  { value: 'data_pipeline', label: 'Pipeline de datos' },
];

export const DETAIL_LEVELS: DetailLevelOption[] = [
  { value: 'summary', label: 'Resumen' },
  { value: 'medium', label: 'Medio' },
  { value: 'detailed', label: 'Detallado' },
];

export const OUTPUT_FORMATS: OutputFormatOption[] = [
  { value: 'phases_table', label: 'Tabla por fases' },
  { value: 'line_items', label: 'Lista plana' },
  { value: 'narrative', label: 'Narrativa' },
];

export interface AcbTierOption {
  value: AcbTier;
  label: string;
}

/** Audience tiers offered when the Actor-Critic-Boss mode is enabled.
 * `default` lets the backend's tier_resolver pick from the transcript. */
export const ACB_TIERS: AcbTierOption[] = [
  { value: 'default', label: 'Automático (según contexto)' },
  { value: 'executive', label: 'Ejecutivo (visión negocio)' },
  { value: 'pm', label: 'Project manager (hitos)' },
  { value: 'developer', label: 'Desarrollador (técnico)' },
];

/** UI metadata per Boss decision (label + css modifier for colour). */
export const BOSS_DECISION_META: Record<BossDecision, { label: string; cssClass: string }> = {
  accept: { label: 'Aceptada', cssClass: 'is-accept' },
  iterate: { label: 'Iterar', cssClass: 'is-iterate' },
  synthesize: { label: 'Síntesis', cssClass: 'is-synthesize' },
};

/** UI metadata per lifecycle status (label + css modifier for colour). */
export const STATUS_META: Record<EstimationStatus, { label: string; cssClass: string }> = {
  editing: { label: 'En edición', cssClass: 'is-editing' },
  running: { label: 'Ejecutando', cssClass: 'is-running' },
  finished: { label: 'Finalizada', cssClass: 'is-finished' },
  error: { label: 'Con error', cssClass: 'is-error' },
};
