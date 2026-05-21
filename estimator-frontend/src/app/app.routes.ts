import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./pages/list/estimation-list.component').then((m) => m.EstimationListComponent),
  },
  {
    path: 'estimations/:id',
    loadComponent: () =>
      import('./pages/detail/estimation-detail.component').then(
        (m) => m.EstimationDetailComponent,
      ),
  },
  { path: '**', redirectTo: '' },
];
