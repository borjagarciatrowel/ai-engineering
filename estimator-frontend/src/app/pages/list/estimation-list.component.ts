import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

import { EstimationListItem, STATUS_META } from '../../models/estimation';
import { EstimationService } from '../../services/estimation.service';

@Component({
  selector: 'app-estimation-list',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [CommonModule, RouterLink, MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  templateUrl: './estimation-list.component.html',
  styleUrl: './estimation-list.component.scss',
})
export class EstimationListComponent implements OnInit {
  private readonly api = inject(EstimationService);
  private readonly router = inject(Router);

  readonly statusMeta = STATUS_META;
  readonly items = signal<EstimationListItem[]>([]);
  readonly loading = signal(true);
  readonly creating = signal(false);
  readonly errorMessage = signal<string | null>(null);

  async ngOnInit(): Promise<void> {
    await this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.errorMessage.set(null);
    try {
      this.items.set(await this.api.list());
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
    } finally {
      this.loading.set(false);
    }
  }

  async createNew(): Promise<void> {
    if (this.creating()) return;
    this.creating.set(true);
    this.errorMessage.set(null);
    try {
      // A new estimation is a new conversation: create the session + its row,
      // then open the detail (conversational interface).
      const { estimation_id } = await this.api.createConversation();
      await this.router.navigate(['/estimations', estimation_id]);
    } catch (err) {
      this.errorMessage.set(err instanceof Error ? err.message : String(err));
      this.creating.set(false);
    }
  }
}
