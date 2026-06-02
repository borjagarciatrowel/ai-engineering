import { Injectable } from '@angular/core';

import {
  AcbTier,
  Conversation,
  DetailLevel,
  EstimationCreate,
  EstimationListItem,
  EstimationRecord,
  EstimationResponse,
  EstimationUpdate,
  OutputFormat,
  ProjectType,
  SessionInfo,
} from '../models/estimation';

export interface ConversationFields {
  transcript: string;
  project_type: ProjectType;
  detail_level: DetailLevel;
  output_format: OutputFormat;
}

@Injectable({ providedIn: 'root' })
export class EstimationService {
  private readonly baseUrl = '/api/v1/estimations';
  private readonly sessionsUrl = '/sessions';

  async list(): Promise<EstimationListItem[]> {
    return this.json<EstimationListItem[]>(await fetch(this.baseUrl));
  }

  async get(id: string): Promise<EstimationRecord> {
    return this.json<EstimationRecord>(await fetch(`${this.baseUrl}/${id}`));
  }

  async create(payload: EstimationCreate): Promise<EstimationRecord> {
    return this.json<EstimationRecord>(
      await fetch(this.baseUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      }),
    );
  }

  async update(id: string, patch: EstimationUpdate): Promise<EstimationRecord> {
    return this.json<EstimationRecord>(
      await fetch(`${this.baseUrl}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      }),
    );
  }

  /** Run the pipeline. Pass reestimate=true to clear caches first (re-estimation). */
  async run(id: string, opts: { reestimate?: boolean } = {}): Promise<EstimationRecord> {
    const qs = opts.reestimate ? '?reestimate=true' : '';
    return this.json<EstimationRecord>(
      await fetch(`${this.baseUrl}/${id}/run${qs}`, { method: 'POST' }),
    );
  }

  async remove(id: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/${id}`, { method: 'DELETE' });
    if (!response.ok) {
      throw new Error(await this.extractError(response));
    }
  }

  // --- Session 5: conversational memory + attachments ---

  /** Start a new conversational estimation: creates the session + its grid/detail
   * row and returns both ids. */
  async createConversation(): Promise<{ session_id: string; estimation_id: string }> {
    return this.json<{ session_id: string; estimation_id: string }>(
      await fetch(this.sessionsUrl, { method: 'POST' }),
    );
  }

  /** Read the current project_metadata + history length for a session. */
  async getSession(id: string): Promise<SessionInfo> {
    return this.json<SessionInfo>(await fetch(`${this.sessionsUrl}/${id}`));
  }

  /** Read the full turn-by-turn history of a session. */
  async getConversation(id: string): Promise<Conversation> {
    return this.json<Conversation>(await fetch(`${this.sessionsUrl}/${id}/conversation`));
  }

  /** Run one conversational turn (multipart: transcript + optional attachments). */
  async estimateInSession(
    id: string,
    fields: ConversationFields,
    files: File[],
  ): Promise<EstimationResponse> {
    const fd = new FormData();
    fd.append('transcript', fields.transcript);
    fd.append('project_type', fields.project_type);
    fd.append('detail_level', fields.detail_level);
    fd.append('output_format', fields.output_format);
    for (const file of files) {
      fd.append('attachments', file, file.name);
    }
    return this.json<EstimationResponse>(
      await fetch(`${this.sessionsUrl}/${id}/estimate`, { method: 'POST', body: fd }),
    );
  }

  /** Run one Actor-Critic-Boss turn. Same multipart contract as
   * {@link estimateInSession} plus an optional audience `tier`; the response
   * carries an `acb` audit trail. `tier='default'` lets the backend resolve it. */
  async estimateInSessionWithAcb(
    id: string,
    fields: ConversationFields,
    files: File[],
    tier: AcbTier = 'default',
  ): Promise<EstimationResponse> {
    const fd = new FormData();
    fd.append('transcript', fields.transcript);
    fd.append('project_type', fields.project_type);
    fd.append('detail_level', fields.detail_level);
    fd.append('output_format', fields.output_format);
    fd.append('tier', tier);
    for (const file of files) {
      fd.append('attachments', file, file.name);
    }
    return this.json<EstimationResponse>(
      await fetch(`${this.sessionsUrl}/${id}/estimate-acb`, { method: 'POST', body: fd }),
    );
  }

  private async json<T>(response: Response): Promise<T> {
    if (!response.ok) {
      throw new Error(await this.extractError(response));
    }
    return (await response.json()) as T;
  }

  /** Map FastAPI error bodies (guardrail 400, validation 422, 404, 502) to a message. */
  private async extractError(response: Response): Promise<string> {
    let detail: unknown;
    try {
      const body = await response.json();
      detail = (body as { detail?: unknown })?.detail ?? body;
    } catch {
      detail = await response.text().catch(() => '');
    }

    if (detail && typeof detail === 'object' && !Array.isArray(detail) && 'message' in detail) {
      const d = detail as { reason?: string; message?: string };
      return d.reason ? `${d.message} (${d.reason})` : d.message ?? `HTTP ${response.status}`;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { loc?: unknown[]; msg?: string };
      const field = first.loc?.[first.loc.length - 1];
      return first.msg ? `${field}: ${first.msg}` : `HTTP ${response.status}`;
    }
    if (typeof detail === 'string' && detail) {
      return detail;
    }
    return `HTTP ${response.status}: ${response.statusText}`;
  }
}
