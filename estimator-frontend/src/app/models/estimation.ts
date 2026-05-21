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

/** UI metadata per lifecycle status (label + css modifier for colour). */
export const STATUS_META: Record<EstimationStatus, { label: string; cssClass: string }> = {
  editing: { label: 'En edición', cssClass: 'is-editing' },
  running: { label: 'Ejecutando', cssClass: 'is-running' },
  finished: { label: 'Finalizada', cssClass: 'is-finished' },
  error: { label: 'Con error', cssClass: 'is-error' },
};
