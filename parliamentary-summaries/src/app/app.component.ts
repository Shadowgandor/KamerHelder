// src/app/app.component.ts - Updated with loading states

import { Component, OnInit, OnDestroy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Observable, Subject, BehaviorSubject, combineLatest } from 'rxjs';
import { map, takeUntil, debounceTime, distinctUntilChanged } from 'rxjs/operators';

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
  EnhancedPartyPosition,
  ProcessedDocument,
  ProcessedPartyPosition,
  ProcessedTopic
} from './models/parliamentary-summary.model';

@Component({
  selector: 'app-root',
  standalone: true,
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

  // Party colors map (static to avoid repeated lookups)
  private static readonly PARTY_COLORS: { [key: string]: string } = {
    'VVD': '#0066CC',
    'PvdA': '#CC0000',
    'GroenLinks-PvdA': '#00AA00',
    'PVV': '#FFD700',
    'CDA': '#00AA55',
    'D66': '#FFAA00',
    'NSC': '#800080',
    'PvdD': '#006600',
    'ChristenUnie': '#0099CC',
    'SGP': '#FF6600',
    'SP': '#CC0000',
    'Minister': '#666666',
    'Voorzitter': '#999999'
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
    // Auto-select first document for demo
    this.documents$.pipe(
      takeUntil(this.destroy$)
    ).subscribe(documents => {
      if (documents.length > 0 && !this.selectedDocumentId) {
        this.onDocumentSelected(documents[0]);
      }
    });

    // Handle error messages
    this.error$.pipe(
      takeUntil(this.destroy$)
    ).subscribe(error => {
      if (error) {
        this.snackBar.open(error, 'Close', {
          duration: 5000,
          panelClass: ['error-snackbar']
        });
      }
    });

    // Show success message when documents are loaded
    this.documentStats$.pipe(
      takeUntil(this.destroy$)
    ).subscribe(stats => {
      if (stats.totalDocuments > 0) {
        this.snackBar.open(
          `Loaded ${stats.totalDocuments} parliamentary documents with ${stats.totalTopics} topics`, 
          'Close', 
          {
            duration: 3000,
            panelClass: ['success-snackbar']
          }
        );
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
    return {
      ...doc,
      formattedDate: this.formatDateOnce(doc.date),
      preview: doc.summary.executive_summary.slice(0, 200),
      topicCount: doc.summary.main_topics.length,
      decisionCount: doc.summary.key_decisions.length,
      hasNextSteps: doc.summary.next_steps?.length > 0,
      nextStepsCount: doc.summary.next_steps?.length || 0,
      hasDecisions: doc.summary.key_decisions.length > 0,
      processingDate: this.formatDateOnce(new Date(doc.summary.processing_info.processing_date)),
      summary: {
        ...doc.summary,
        main_topics: doc.summary.main_topics.map(topic => ({
          ...topic,
          hasContext: this.hasTopicContextComputed(topic),
          partyPositionsArray: this.convertPartyPositions(topic.party_positions)
        }))
      }
    };
  }

  // Convert party positions to array for easier iteration
  private convertPartyPositions(positions: { [key: string]: EnhancedPartyPosition | string }): ProcessedPartyPosition[] {
    return Object.keys(positions).map(party => {
      const proposals = this.getSpecificProposals(positions[party]);
      return {
        party,
        color: this.getPartyBadgeColorOnce(party),
        mainPosition: this.getPartyPosition(positions[party]),
        proposals: proposals,
        hasProposals: (proposals?.length ?? 0) > 0,
        reasoning: this.getReasoning(positions[party]),
        evidence: this.getEvidence(positions[party])
      };
    });
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

  // Get party color once
  private getPartyBadgeColorOnce(partyName: string): string {
    return AppComponent.PARTY_COLORS[partyName] || '#666666';
  }

  // Fixed: Properly update selectedDocumentId and notify observable
  onDocumentSelected(document: ProcessedDocument): void {
    console.log('Document selected:', document.title); // Debug log
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

  // Enhanced party position methods (kept for compatibility)
  getPartyPosition(position: EnhancedPartyPosition | string): string {
    if (typeof position === 'string') {
      return position;
    }
    return position.position || 'Position not specified';
  }

  getSpecificProposals(position: EnhancedPartyPosition | string): string[] | null {
    if (typeof position === 'string') {
      return null;
    }
    return position.specific_proposals || null;
  }

  getReasoning(position: EnhancedPartyPosition | string): string | null {
    if (typeof position === 'string') {
      return null;
    }
    return position.reasoning || null;
  }

  getEvidence(position: EnhancedPartyPosition | string): string | null {
    if (typeof position === 'string') {
      return null;
    }
    return position.key_evidence || null;
  }

  // New methods for file management
  async onRefreshDocuments(): Promise<void> {
    await this.summaryService.refreshDocuments();
    this.snackBar.open('Documents refreshed', 'Close', { duration: 2000 });
  }

  async onLoadSpecificFiles(): Promise<void> {
    // This would typically open a dialog or file picker
    // For now, you can hardcode some filenames for testing
    const filenames = [
      'deepseek_summary_84d94edd-499f-4d88-9e06-c5c0cd71b1c4.json',
      // Add more filenames as needed
    ];
    
    try {
      await this.summaryService.loadSpecificFiles(filenames);
      this.snackBar.open(`Attempted to load ${filenames.length} additional files`, 'Close', { duration: 3000 });
    } catch (error) {
      this.snackBar.open('Error loading additional files', 'Close', { duration: 3000 });
    }
  }

  // Helper method to show document statistics
  showDocumentStats(): void {
    this.documentStats$.pipe(takeUntil(this.destroy$)).subscribe(stats => {
      const message = `${stats.totalDocuments} documents, ${stats.totalTopics} topics, ${stats.uniqueParties} parties`;
      this.snackBar.open(message, 'Close', { duration: 5000 });
    });
  }

  // Optimized trackBy functions
  trackByDocumentId(index: number, doc: ProcessedDocument): string {
    return doc.id;
  }

  trackByTopicName(index: number, topic: ProcessedTopic): string {
    return topic.topic;
  }

  trackByPartyName(index: number, position: ProcessedPartyPosition): string {
    return position.party;
  }

  trackByFilterName(index: number, filter: TopicFilter | PartyFilter): string {
    return filter.name;
  }

  trackByIndex(index: number): number {
    return index;
  }

  // Legacy method for backward compatibility
  getPartyBadgeColor(partyName: string): string {
    return this.getPartyBadgeColorOnce(partyName);
  }
}