import { CommonModule } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
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
  ProjectType,
  STATUS_META,
} from '../../models/estimation';
import { EstimationService } from '../../services/estimation.service';

const DESCRIPTION_MAX = 80000;
const OUT_OF_SCOPE_PREFIX = 'Out of scope:';
const LOW_CONFIDENCE_THRESHOLD = 30;
const POLL_INTERVAL_MS = 2500;

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
export class EstimationDetailComponent implements OnInit, OnDestroy {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(EstimationService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialog);

  readonly statusMeta = STATUS_META;
  readonly projectTypes = PROJECT_TYPES;
  readonly detailLevels = DETAIL_LEVELS;
  readonly outputFormats = OUTPUT_FORMATS;
  readonly descriptionMax = DESCRIPTION_MAX;
  readonly lowConfidenceThreshold = LOW_CONFIDENCE_THRESHOLD;

  readonly record = signal<EstimationRecord | null>(null);
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly busyLabel = signal('');
  readonly errorMessage = signal<string | null>(null);

  readonly status = computed(() => this.record()?.status ?? null);
  readonly isEditing = computed(() => this.status() === 'editing');
  readonly isRunning = computed(() => this.status() === 'running' || this.busy());
  readonly isFinished = computed(() => this.status() === 'finished');
  readonly isError = computed(() => this.status() === 'error');

  readonly form = this.fb.nonNullable.group({
    title: ['', [Validators.required, Validators.maxLength(200)]],
    project_type: ['web_saas' as ProjectType, Validators.required],
    detail_level: ['medium' as DetailLevel, Validators.required],
    output_format: ['phases_table' as OutputFormat, Validators.required],
    description: ['', [Validators.maxLength(DESCRIPTION_MAX)]],
  });

  private id = '';
  private pollHandle: ReturnType<typeof setInterval> | null = null;

  async ngOnInit(): Promise<void> {
    this.id = this.route.snapshot.paramMap.get('id') ?? '';
    await this.load();
  }

  ngOnDestroy(): void {
    this.stopPoll();
  }

  private async load(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set(null);
    try {
      const rec = await this.api.get(this.id);
      this.applyRecord(rec);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.loading.set(false);
    }
  }

  private applyRecord(rec: EstimationRecord): void {
    this.record.set(rec);
    this.form.patchValue({
      title: rec.title,
      project_type: rec.project_type,
      detail_level: rec.detail_level,
      output_format: rec.output_format,
      description: rec.description,
    });
    if (rec.status === 'running') {
      this.startPoll();
    } else {
      this.stopPoll();
    }
  }

  async save(): Promise<void> {
    if (this.busy() || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.busyLabel.set('Guardando…');
    this.errorMessage.set(null);
    try {
      const rec = await this.api.update(this.id, this.form.getRawValue());
      this.applyRecord(rec);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.busy.set(false);
    }
  }

  /** Persist the latest prompt then run. reestimate=true clears caches first. */
  async runFlow(reestimate: boolean): Promise<void> {
    if (this.busy() || this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.busyLabel.set(reestimate ? 'Reestimando…' : 'Ejecutando…');
    this.errorMessage.set(null);
    try {
      await this.api.update(this.id, this.form.getRawValue());
      const rec = await this.api.run(this.id, { reestimate });
      this.applyRecord(rec);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
      await this.load();
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
    this.busyLabel.set('Eliminando…');
    try {
      await this.api.remove(this.id);
      await this.router.navigate(['/']);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
      this.busy.set(false);
    }
  }

  private startPoll(): void {
    if (this.pollHandle) return;
    this.pollHandle = setInterval(async () => {
      try {
        const rec = await this.api.get(this.id);
        if (rec.status !== 'running') {
          this.applyRecord(rec); // also stops the poll
        } else {
          this.record.set(rec);
        }
      } catch {
        /* keep polling; transient errors are ignored */
      }
    }, POLL_INTERVAL_MS);
  }

  private stopPoll(): void {
    if (this.pollHandle) {
      clearInterval(this.pollHandle);
      this.pollHandle = null;
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

  descriptionError(): string | null {
    const ctrl = this.form.controls.description;
    if (!ctrl.touched) return null;
    if (ctrl.hasError('maxlength')) return `Máximo ${DESCRIPTION_MAX} caracteres`;
    return null;
  }
}
