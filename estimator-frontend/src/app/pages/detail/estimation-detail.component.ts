import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDialog, MatDialogModule } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatSelectModule } from '@angular/material/select';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import {
  ConfirmDeleteDialogComponent,
  ConfirmDeleteData,
} from '../../components/confirm-delete-dialog.component';
import {
  DETAIL_LEVELS,
  DetailLevel,
  EstimationRecord,
  EstimationResult,
  OUTPUT_FORMATS,
  OutputFormat,
  PROJECT_TYPES,
  ProjectMetadata,
  ProjectType,
  STATUS_META,
} from '../../models/estimation';
import { EstimationService } from '../../services/estimation.service';

const TRANSCRIPT_MIN = 20;
const TRANSCRIPT_MAX = 80000;
const OUT_OF_SCOPE_PREFIX = 'Out of scope:';
const LOW_CONFIDENCE_THRESHOLD = 30;

/** One rendered turn of the conversation. */
interface DetailConversationTurn {
  transcript: string;
  result: EstimationResult | null;
}

@Component({
  selector: 'app-estimation-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterLink,
    MatButtonModule,
    MatCardModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatProgressBarModule,
    MatProgressSpinnerModule,
    MatSelectModule,
  ],
  templateUrl: './estimation-detail.component.html',
  styleUrl: './estimation-detail.component.scss',
})
export class EstimationDetailComponent implements OnInit {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(EstimationService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);

  readonly statusMeta = STATUS_META;
  readonly projectTypes = PROJECT_TYPES;
  readonly detailLevels = DETAIL_LEVELS;
  readonly outputFormats = OUTPUT_FORMATS;
  readonly transcriptMax = TRANSCRIPT_MAX;
  readonly transcriptMin = TRANSCRIPT_MIN;
  readonly lowConfidenceThreshold = LOW_CONFIDENCE_THRESHOLD;

  readonly record = signal<EstimationRecord | null>(null);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly errorMessage = signal<string | null>(null);

  readonly metadata = signal<ProjectMetadata | null>(null);
  readonly turns = signal<DetailConversationTurn[]>([]);
  readonly files = signal<File[]>([]);

  readonly status = computed(() => this.record()?.status ?? null);
  readonly isConversational = computed(() => !!this.record()?.session_id);
  readonly metadataIsEmpty = computed(() => {
    const m = this.metadata();
    return (
      !m ||
      (!m.project_name &&
        m.assumed_team_size == null &&
        m.mentioned_technologies.length === 0 &&
        !m.agreed_scope)
    );
  });

  readonly form = this.fb.nonNullable.group({
    transcript: ['', [Validators.required, Validators.minLength(TRANSCRIPT_MIN)]],
    project_type: ['web_saas' as ProjectType, Validators.required],
    detail_level: ['medium' as DetailLevel, Validators.required],
    output_format: ['phases_table' as OutputFormat, Validators.required],
  });

  private id = '';
  private sessionId: string | null = null;

  async ngOnInit(): Promise<void> {
    this.id = this.route.snapshot.paramMap.get('id') ?? '';
    await this.load();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set(null);
    try {
      const rec = await this.api.get(this.id);
      this.record.set(rec);
      this.sessionId = rec.session_id;
      // Reuse the last turn's parameters as the composer defaults.
      this.form.patchValue({
        project_type: rec.project_type,
        detail_level: rec.detail_level,
        output_format: rec.output_format,
      });
      if (rec.session_id) {
        await this.loadConversation(rec.session_id);
      }
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.loading.set(false);
    }
  }

  private async loadConversation(sessionId: string): Promise<void> {
    const conv = await this.api.getConversation(sessionId);
    this.metadata.set(conv.metadata);
    const turns: DetailConversationTurn[] = [];
    for (let i = 0; i < conv.messages.length; i += 2) {
      const user = conv.messages[i];
      const assistant = conv.messages[i + 1];
      let result: EstimationResult | null = null;
      if (assistant) {
        try {
          result = JSON.parse(assistant.content) as EstimationResult;
        } catch {
          result = null;
        }
      }
      turns.push({ transcript: user?.content ?? '', result });
    }
    this.turns.set(turns);
  }

  onFilesSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    if (!input.files) return;
    this.files.set([...this.files(), ...Array.from(input.files)]);
    input.value = '';
  }

  removeFile(index: number): void {
    this.files.set(this.files().filter((_, i) => i !== index));
  }

  async send(): Promise<void> {
    if (!this.sessionId || this.busy() || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.errorMessage.set(null);
    const fields = this.form.getRawValue();
    try {
      await this.api.estimateInSession(this.sessionId, fields, this.files());
      await this.loadConversation(this.sessionId);
      // The mirror updates title/status; refresh the header.
      this.record.set(await this.api.get(this.id));
      this.form.controls.transcript.reset('');
      this.files.set([]);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy.set(false);
    }
  }

  async confirmDelete(): Promise<void> {
    const rec = this.record();
    if (!rec) return;
    const ref = this.dialog.open<ConfirmDeleteDialogComponent, ConfirmDeleteData, boolean>(
      ConfirmDeleteDialogComponent,
      { data: { title: rec.title }, width: '440px', autoFocus: 'dialog' },
    );
    const confirmed = await firstValueFrom(ref.afterClosed());
    if (!confirmed) return;
    this.busy.set(true);
    try {
      await this.api.remove(this.id);
      await this.router.navigate(['/']);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
      this.busy.set(false);
    }
  }

  isOutOfScope(result: EstimationResult): boolean {
    return result.summary.startsWith(OUT_OF_SCOPE_PREFIX);
  }

  formatEur(value: number): string {
    return new Intl.NumberFormat('es-ES', {
      style: 'currency',
      currency: 'EUR',
      maximumFractionDigits: 0,
    }).format(value);
  }

  formatUsd(value: number | null): string {
    return value == null ? '—' : `$${value.toFixed(4)}`;
  }

  transcriptError(): string | null {
    const ctrl = this.form.controls.transcript;
    if (!ctrl.touched) return null;
    if (ctrl.hasError('required')) return 'La transcripción es obligatoria';
    if (ctrl.hasError('minlength')) return `Mínimo ${TRANSCRIPT_MIN} caracteres`;
    return null;
  }
}
