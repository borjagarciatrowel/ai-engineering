import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatDividerModule } from '@angular/material/divider';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatMenuModule } from '@angular/material/menu';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSelectModule } from '@angular/material/select';
import { MatToolbarModule } from '@angular/material/toolbar';
import { MarkdownComponent } from 'ngx-markdown';

import {
  DETAIL_LEVELS,
  DetailLevel,
  EstimationRequest,
  OUTPUT_FORMATS,
  OutputFormat,
  PROJECT_TYPES,
  ProjectType,
  StreamMetrics,
} from './models/estimation';
import { EstimationService } from './services/estimation.service';

@Component({
  selector: 'app-root',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatCardModule,
    MatDividerModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
    MatMenuModule,
    MatProgressBarModule,
    MatSelectModule,
    MatToolbarModule,
    MarkdownComponent,
  ],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss',
})
export class AppComponent {
  private readonly fb = inject(FormBuilder);
  private readonly api = inject(EstimationService);

  readonly projectTypes = PROJECT_TYPES;
  readonly detailLevels = DETAIL_LEVELS;
  readonly outputFormats = OUTPUT_FORMATS;

  readonly availablePromptVersions: readonly string[] = ['v1'];
  readonly promptVersion = signal<string>('v1');

  readonly form = this.fb.nonNullable.group({
    description: ['', [Validators.required, Validators.minLength(20), Validators.maxLength(2000)]],
    project_type: ['web_saas' as ProjectType, Validators.required],
    detail_level: ['medium' as DetailLevel, Validators.required],
    output_format: ['phases_table' as OutputFormat, Validators.required],
  });

  readonly streaming = signal(false);
  readonly output = signal('');
  readonly errorMessage = signal<string | null>(null);
  readonly metrics = signal<StreamMetrics | null>(null);

  async submit(): Promise<void> {
    if (this.form.invalid || this.streaming()) {
      this.form.markAllAsTouched();
      return;
    }

    const payload: EstimationRequest = this.form.getRawValue();
    this.output.set('');
    this.metrics.set(null);
    this.errorMessage.set(null);
    this.streaming.set(true);

    try {
      for await (const event of this.api.stream(payload, this.promptVersion())) {
        if (event.type === 'token' && event.text) {
          this.output.update((prev) => prev + event.text);
        } else if (event.type === 'metrics' && event.metrics) {
          this.metrics.set(event.metrics);
        } else if (event.type === 'error' && event.error) {
          this.errorMessage.set(event.error);
        }
      }
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.streaming.set(false);
    }
  }

  reset(): void {
    this.output.set('');
    this.metrics.set(null);
    this.errorMessage.set(null);
    this.form.reset({
      description: '',
      project_type: 'web_saas',
      detail_level: 'medium',
      output_format: 'phases_table',
    });
  }

  descriptionError(): string | null {
    const ctrl = this.form.controls.description;
    if (!ctrl.touched) return null;
    if (ctrl.hasError('required')) return 'La descripción es obligatoria';
    if (ctrl.hasError('minlength')) return 'Mínimo 20 caracteres';
    if (ctrl.hasError('maxlength')) return 'Máximo 2000 caracteres';
    return null;
  }
}
