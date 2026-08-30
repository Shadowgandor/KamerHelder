// src/main.ts
import { bootstrapApplication } from '@angular/platform-browser';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { provideAnimations } from '@angular/platform-browser/animations';
import { importProvidersFrom, provideZoneChangeDetection } from '@angular/core';

// Material Design theme and core modules
import { MatNativeDateModule } from '@angular/material/core';

import { AppComponent } from './app/app.component';
import { provideAnimationsAsync } from '@angular/platform-browser/animations/async';

bootstrapApplication(AppComponent, {
  providers: [
    provideZoneChangeDetection(),provideHttpClient(withXhr()),
    provideAnimations(),
    
    // Material Design providers
    importProvidersFrom(MatNativeDateModule),
  ]
}).catch(err => console.error(err));