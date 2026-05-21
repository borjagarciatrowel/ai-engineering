import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import {
  MAT_DIALOG_DATA,
  MatDialogModule,
  MatDialogRef,
} from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

export interface ConfirmDeleteData {
  title: string;
}

@Component({
  selector: 'app-confirm-delete-dialog',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    MatButtonModule,
    MatDialogModule,
    MatFormFieldModule,
    MatIconModule,
    MatInputModule,
  ],
  template: `
    <h2 mat-dialog-title class="confirm-title">
      <mat-icon>warning</mat-icon> Eliminar estimación
    </h2>
    <mat-dialog-content>
      <p class="confirm-text">
        Esta acción es <strong>permanente</strong>. Se borrará la estimación y su resultado.
      </p>
      <p class="confirm-instruction">
        Escribe <strong>{{ data.title }}</strong> para confirmar:
      </p>
      <mat-form-field appearance="outline">
        <input
          matInput
          [ngModel]="typed()"
          (ngModelChange)="typed.set($event)"
          [placeholder]="data.title"
          autocomplete="off"
        />
      </mat-form-field>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="cancel()">Cancelar</button>
      <button mat-flat-button color="warn" [disabled]="!matches()" (click)="confirm()">
        <mat-icon>delete</mat-icon> Eliminar
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .confirm-title {
        display: flex;
        align-items: center;
        gap: 0.5rem;
      }
      .confirm-title mat-icon {
        color: var(--danger);
      }
      .confirm-text {
        color: var(--text-secondary);
        margin: 0 0 0.75rem;
      }
      .confirm-instruction {
        color: var(--text-secondary);
        margin: 0 0 0.5rem;
      }
      .confirm-instruction strong {
        color: var(--text-primary);
      }
      mat-form-field {
        width: 100%;
      }
      [mat-flat-button][color='warn'] {
        --mdc-filled-button-container-color: var(--danger);
        --mdc-filled-button-label-text-color: #0a0c14;
      }
      [mat-flat-button][color='warn'] mat-icon {
        margin-right: 0.3rem;
        font-size: 1.05rem;
        width: 1.05rem;
        height: 1.05rem;
      }
    `,
  ],
})
export class ConfirmDeleteDialogComponent {
  private readonly ref = inject(MatDialogRef<ConfirmDeleteDialogComponent, boolean>);
  readonly data = inject<ConfirmDeleteData>(MAT_DIALOG_DATA);

  readonly typed = signal('');
  readonly matches = computed(() => this.typed().trim() === this.data.title.trim());

  cancel(): void {
    this.ref.close(false);
  }

  confirm(): void {
    if (this.matches()) {
      this.ref.close(true);
    }
  }
}
