import { Injectable } from '@angular/core';

import {
  EstimationCreate,
  EstimationListItem,
  EstimationRecord,
  EstimationUpdate,
} from '../models/estimation';

@Injectable({ providedIn: 'root' })
export class EstimationService {
  private readonly baseUrl = '/api/v1/estimations';

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
