import { Injectable } from '@angular/core';

import { EstimationRequest, StreamMetrics } from '../models/estimation';

export interface StreamEvent {
  type: 'token' | 'metrics' | 'error' | 'done';
  text?: string;
  metrics?: StreamMetrics;
  error?: string;
}

@Injectable({ providedIn: 'root' })
export class EstimationService {
  private readonly baseUrl = '/api/v1';

  async *stream(request: EstimationRequest): AsyncGenerator<StreamEvent, void, void> {
    const startedAt = performance.now();
    const response = await fetch(`${this.baseUrl}/estimate/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const detail = await response.text().catch(() => '');
      yield { type: 'error', error: `HTTP ${response.status}: ${detail || response.statusText}` };
      return;
    }
    if (!response.body) {
      yield { type: 'error', error: 'El backend no devolvió cuerpo de respuesta.' };
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let promptVersion = 'v1';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });

        let newlineIndex = buffer.indexOf('\n');
        while (newlineIndex !== -1) {
          const rawLine = buffer.slice(0, newlineIndex).trim();
          buffer = buffer.slice(newlineIndex + 1);
          newlineIndex = buffer.indexOf('\n');
          if (!rawLine) {
            continue;
          }
          const event = this.parseLine(rawLine, promptVersion, startedAt);
          if (event.type === 'metrics' && event.metrics) {
            promptVersion = event.metrics.prompt_version;
          } else if (event.type === 'token' && event.text === '__PROMPT_VERSION_UPDATE__') {
            promptVersion = event.error ?? promptVersion;
            continue;
          }
          yield event;
        }
      }
      const tail = buffer.trim();
      if (tail) {
        yield this.parseLine(tail, promptVersion, startedAt);
      }
    } finally {
      reader.releaseLock();
    }

    yield { type: 'done' };
  }

  private parseLine(line: string, promptVersion: string, startedAt: number): StreamEvent {
    let chunk: Record<string, unknown>;
    try {
      chunk = JSON.parse(line);
    } catch {
      return { type: 'error', error: `Línea NDJSON inválida: ${line}` };
    }

    if (typeof chunk['t'] === 'string') {
      return { type: 'token', text: chunk['t'] as string };
    }
    if (chunk['done'] === true) {
      const usage = (chunk['usage'] as Record<string, number>) ?? {};
      return {
        type: 'metrics',
        metrics: {
          prompt_version: promptVersion,
          model: (chunk['model'] as string) ?? 'unknown',
          provider: (chunk['provider'] as string) ?? 'unknown',
          input_tokens: usage['input_tokens'] ?? 0,
          output_tokens: usage['output_tokens'] ?? 0,
          total_tokens: usage['total_tokens'] ?? 0,
          response_time_ms: Math.round(performance.now() - startedAt),
        },
      };
    }
    if (typeof chunk['prompt_version'] === 'string') {
      return {
        type: 'metrics',
        metrics: {
          prompt_version: chunk['prompt_version'] as string,
          model: 'pending',
          provider: 'pending',
          input_tokens: 0,
          output_tokens: 0,
          total_tokens: 0,
          response_time_ms: 0,
        },
      };
    }
    if (typeof chunk['error'] === 'string') {
      return { type: 'error', error: chunk['error'] as string };
    }
    return { type: 'error', error: `Chunk NDJSON desconocido: ${line}` };
  }
}
