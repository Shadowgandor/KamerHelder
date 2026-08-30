// src/app/app.component.ts - Updated with loading states

import { Component, OnInit, OnDestroy, ChangeDetectionStrategy, inject } from '@angular/core';
import { CommonModule, Location } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subject, BehaviorSubject, combineLatest } from 'rxjs';
import { map, take, takeUntil, debounceTime, distinctUntilChanged } from 'rxjs/operators';

// Material Design imports
import { MatToolbarModule } from '@angular/material/toolbar';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatExpansionModule } from '@angular/material/expansion';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatDividerModule } from '@angular/material/divider';
import { MatBadgeModule } from '@angular/material/badge';
import { MatTooltipModule } from '@angular/material/tooltip';
import { MatListModule } from '@angular/material/list';
import { MatRippleModule } from '@angular/material/core';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { MatSnackBarModule, MatSnackBar } from '@angular/material/snack-bar';

import { SummaryService } from './services/summary.service';
import {
  ParliamentaryDocument,
  TopicFilter,
  PartyFilter,
  SearchFilter,
  SummaryDisplayOptions,
  TopicDisplayMode,
  ProcessedDocument,
  FactCheckAssessment,
  normalizePartyPositions
} from './models/parliamentary-summary.model';

@Component({
    selector: 'app-root',
    imports: [
        CommonModule,
        FormsModule,
        MatToolbarModule,
        MatCardModule,
        MatButtonModule,
        MatIconModule,
        MatChipsModule,
        MatExpansionModule,
        MatCheckboxModule,
        MatInputModule,
        MatFormFieldModule,
        MatSidenavModule,
        MatDividerModule,
        MatBadgeModule,
        MatTooltipModule,
        MatListModule,
        MatRippleModule,
        MatProgressSpinnerModule,
        MatProgressBarModule,
        MatSnackBarModule
    ],
    templateUrl: './app.component.html',
    changeDetection: ChangeDetectionStrategy.Eager,
    styleUrls: ['./app.component.scss']
})
export class AppComponent implements OnInit, OnDestroy {
  title = 'Parliamentary Summaries';
  
  // Optimized observables with preprocessing
  documents$: Observable<ProcessedDocument[]>;
  topicFilters$: Observable<TopicFilter[]>;
  partyFilters$: Observable<PartyFilter[]>;
  searchFilter$: Observable<SearchFilter>;
  selectedDocument$: Observable<ProcessedDocument | null>;
  loading$: Observable<boolean>;
  error$: Observable<string | null>;
  documentStats$: Observable<any>;
  
  // Fixed: Use BehaviorSubject for selectedDocumentId
  private selectedDocumentIdSubject = new BehaviorSubject<string | null>(null);
  selectedDocumentId: string | null = null;
  showFilters = false;
  allTopicsExpanded = false;
  
  // Search properties
  searchQuery = '';
  searchOptions = {
    includeContext: true,
    includeReasoning: true,
    includeProposals: true
  };
  
  // Debounced search subject
  private searchSubject = new Subject<string>();
  private destroy$ = new Subject<void>();

  // Deep links use the hash fragment (#/vergadering/<id>). GitHub Pages serves
  // static files with no SPA fallback, so a path-based URL would 404 when
  // opened or refreshed directly; a fragment never reaches the server.
  private location = inject(Location);
  private static readonly ROUTE_PREFIX = '#/vergadering/';
  
  // Enhanced display options
  displayOptions: SummaryDisplayOptions = {
    topicMode: {
      showContext: true,
      showSpecificProposals: true,
      showReasoning: true,
      showEvidence: true
    },
    expandedTopics: new Set<string>(),
    showAllParties: true,
    groupByTopic: true
  };

  constructor(
    private summaryService: SummaryService,
    private snackBar: MatSnackBar
  ) {
    // Set up preprocessed documents observable
    this.documents$ = this.summaryService.filteredDocuments$.pipe(
      map(documents => documents.map(doc => this.preprocessDocument(doc)))
    );
    
    this.topicFilters$ = this.summaryService.topicFilters$;
    this.partyFilters$ = this.summaryService.partyFilters$;
    this.searchFilter$ = this.summaryService.searchFilter$;
    this.loading$ = this.summaryService.loading$;
    this.error$ = this.summaryService.error$;
    this.documentStats$ = this.summaryService.getDocumentStats();
    
    // Fixed: Create proper selected document observable
    this.selectedDocument$ = combineLatest([
      this.documents$,
      this.selectedDocumentIdSubject.asObservable()
    ]).pipe(
      map(([documents, selectedId]) => 
        selectedId ? documents.find(doc => doc.id === selectedId) || null : null
      )
    );
    
    // Set up debounced search
    this.searchSubject.pipe(
      debounceTime(300),
      distinctUntilChanged(),
      takeUntil(this.destroy$)
    ).subscribe(query => {
      this.searchQuery = query;
      this.summaryService.updateSearchFilter({ query });
    });
  }

  ngOnInit(): void {
    // Restore the meeting named in the URL, else fall back to the newest one.
    this.documents$.pipe(
      takeUntil(this.destroy$)
    ).subscribe(documents => {
      if (documents.length === 0 || this.selectedDocumentId) {
        return;
      }
      const requested = this.documentIdFromUrl();
      const match = requested
        ? documents.find(doc => doc.id === requested)
        : undefined;

      if (match) {
        this.selectDocument(match);
      } else {
        this.onDocumentSelected(documents[0]);
      }
    });

    // Keep the view in step with the browser's back and forward buttons.
    this.location.onUrlChange(() => {
      const id = this.documentIdFromUrl();
      if (!id || id === this.selectedDocumentId) {
        return;
      }
      this.documents$.pipe(take(1), takeUntil(this.destroy$)).subscribe(documents => {
        const match = documents.find(doc => doc.id === id);
        if (match) {
          this.selectDocument(match);
        }
      });
    });

    // Handle error messages
    this.error$.pipe(
      takeUntil(this.destroy$)
    ).subscribe(error => {
      if (error) {
        this.snackBar.open(error, 'Sluiten', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
      }
    });
  }

  ngOnDestroy(): void {
    this.destroy$.next();
    this.destroy$.complete();
    this.selectedDocumentIdSubject.complete();
  }

  // Preprocessing method for documents
  private preprocessDocument(doc: ParliamentaryDocument): ProcessedDocument {
    const factChecks = doc.summary.fact_checks ?? [];

    return {
      ...doc,
      formattedDate: this.formatDateOnce(doc.date),
      preview: doc.summary.executive_summary.slice(0, 200),
      topicCount: doc.summary.main_topics.length,
      decisionCount: doc.summary.key_decisions.length,
      hasNextSteps: doc.summary.next_steps?.length > 0,
      nextStepsCount: doc.summary.next_steps?.length || 0,
      hasDecisions: doc.summary.key_decisions.length > 0,
      factCheckCount: factChecks.length,
      hasFactChecks: factChecks.length > 0,
      processingDate: this.formatDateOnce(new Date(doc.summary.processing_info.processing_date)),
      summary: {
        ...doc.summary,
        main_topics: doc.summary.main_topics.map(topic => ({
          ...topic,
          hasContext: this.hasTopicContextComputed(topic),
          partyPositionsArray: normalizePartyPositions(topic.party_positions)
        }))
      }
    };
  }

  // Compute context once
  private hasTopicContextComputed(topic: any): boolean {
    return !!(topic.context?.why_discussed || 
             topic.context?.background || 
             topic.context?.stakes ||
             topic.context?.trigger);
  }

  // Format date once
  private formatDateOnce(date: Date): string {
    return date.toLocaleDateString('nl-NL', { 
      weekday: 'long', 
      year: 'numeric', 
      month: 'long', 
      day: 'numeric' 
    });
  }

  // Fixed: Properly update selectedDocumentId and notify observable
  onDocumentSelected(document: ProcessedDocument): void {
    this.selectDocument(document);
    this.location.go(AppComponent.ROUTE_PREFIX + document.id);
  }

  /** Select without touching history — used when restoring from the URL. */
  private selectDocument(document: ProcessedDocument): void {
    this.selectedDocumentId = document.id;
    this.selectedDocumentIdSubject.next(document.id);
    
    // Reset expanded topics for new document
    this.displayOptions.expandedTopics.clear();
    this.allTopicsExpanded = false;
    
    // Expand first few topics by default
    if (document.summary.main_topics.length > 0) {
      document.summary.main_topics.slice(0, 2).forEach(topic => {
        this.displayOptions.expandedTopics.add(topic.topic);
      });
      this.updateExpandAllState();
    }
  }

  // Debounced search handler
  onSearchChangeDebounced(value: string): void {
    this.searchSubject.next(value);
  }

  updateSearchOption(option: string, event: any): void {
    console.log('Search option updated:', option, event.checked); // Debug log
    const checked = event.checked;
    this.searchOptions[option as keyof typeof this.searchOptions] = checked;
    const update: Partial<SearchFilter> = {};
    (update as any)[option] = checked;
    this.summaryService.updateSearchFilter(update);
  }

  onTopicFilterChange(topicName: string, selected: boolean): void {
    console.log('Topic filter changed:', topicName, selected); // Debug log
    this.summaryService.updateTopicFilter(topicName, selected);
  }

  onPartyFilterChange(partyName: string, selected: boolean): void {
    console.log('Party filter changed:', partyName, selected); // Debug log
    this.summaryService.updatePartyFilter(partyName, selected);
  }

  toggleFilters(): void {
    console.log('Toggling filters, current state:', this.showFilters); // Debug log
    this.showFilters = !this.showFilters;
  }

  // Enhanced display option methods
  toggleDisplayOption(option: keyof TopicDisplayMode, event: any): void {
    console.log('Display option toggled:', option, event.checked); // Debug log
    const checked = event.checked;
    this.displayOptions.topicMode[option] = checked;
  }

  // Fixed topic expansion methods
  onTopicPanelOpened(topicName: string): void {
    setTimeout(() => {
      this.displayOptions.expandedTopics.add(topicName);
      this.updateExpandAllState();
    });
  }

  onTopicPanelClosed(topicName: string): void {
    setTimeout(() => {
      this.displayOptions.expandedTopics.delete(topicName);
      this.updateExpandAllState();
    });
  }

  private updateExpandAllState(): void {
    // This method is now simpler as we work with selectedDocument$
    // The state will be managed by the observable
  }

  isTopicExpanded(topicName: string): boolean {
    return this.displayOptions.expandedTopics.has(topicName);
  }

  toggleExpandAll(): void {
    // This will be handled in the template with async pipe
  }

  async onRefreshDocuments(): Promise<void> {
    await this.summaryService.refreshDocuments();
    this.snackBar.open('Documenten vernieuwd', 'Sluiten', { duration: 2000 });
  }

  /** The meeting id in the current URL fragment, if there is one. */
  private documentIdFromUrl(): string | null {
    const hash = window.location.hash;
    return hash.startsWith(AppComponent.ROUTE_PREFIX)
      ? decodeURIComponent(hash.slice(AppComponent.ROUTE_PREFIX.length))
      : null;
  }

  /** Human-readable Dutch label for a fact-check verdict. */
  assessmentLabel(assessment: FactCheckAssessment): string {
    const labels: Record<FactCheckAssessment, string> = {
      onjuist: 'Onjuist',
      misleidend: 'Misleidend',
      grotendeels_juist: 'Grotendeels juist',
      onverifieerbaar: 'Niet te verifiëren'
    };
    return labels[assessment] ?? assessment;
  }

  /** Show a source link by its domain rather than a long URL. */
  sourceLabel(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url;
    }
  }


}