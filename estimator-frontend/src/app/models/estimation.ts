export type ProjectType = 'mobile_app' | 'web_saas' | 'internal_tool' | 'data_pipeline';
export type DetailLevel = 'summary' | 'medium' | 'detailed';
export type OutputFormat = 'phases_table' | 'line_items' | 'narrative';

export interface EstimationRequest {
  description: string;
  project_type: ProjectType;
  detail_level: DetailLevel;
  output_format: OutputFormat;
}

export interface StreamMetrics {
  prompt_version: string;
  model: string;
  provider: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  response_time_ms: number;
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
