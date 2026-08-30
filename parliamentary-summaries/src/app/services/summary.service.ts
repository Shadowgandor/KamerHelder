// src/app/services/summary.service.ts

import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject, combineLatest, map, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { 
  ParliamentarySummary, 
  ParliamentaryDocument, 
  TopicFilter, 
  PartyFilter, 
  SearchFilter,
  EnhancedTopic,
  normalizePartyPositions
} from '../models/parliamentary-summary.model';

interface SummaryFileInfo {
  filename: string;
  model: string;
  id: string;
}

@Injectable({
  providedIn: 'root'
})
export class SummaryService {
  private documentsSubject = new BehaviorSubject<ParliamentaryDocument[]>([]);
  private topicFiltersSubject = new BehaviorSubject<TopicFilter[]>([]);
  private partyFiltersSubject = new BehaviorSubject<PartyFilter[]>([]);
  private loadingSubject = new BehaviorSubject<boolean>(false);
  private errorSubject = new BehaviorSubject<string | null>(null);
  private searchFilterSubject = new BehaviorSubject<SearchFilter>({
    query: '',
    includeTopics: true,
    includePositions: true,
    includeDecisions: true,
    includeContext: true,
    includeReasoning: true
  });

  public documents$ = this.documentsSubject.asObservable();
  public topicFilters$ = this.topicFiltersSubject.asObservable();
  public partyFilters$ = this.partyFiltersSubject.asObservable();
  public searchFilter$ = this.searchFilterSubject.asObservable();
  public loading$ = this.loadingSubject.asObservable();
  public error$ = this.errorSubject.asObservable();

  // Enhanced filtered documents based on current filters
  public filteredDocuments$ = combineLatest([
    this.documents$,
    this.topicFilters$,
    this.partyFilters$,
    this.searchFilter$
  ]).pipe(
    map(([documents, topicFilters, partyFilters, searchFilter]) => 
      this.applyEnhancedFilters(documents, topicFilters, partyFilters, searchFilter)
    )
  );

  constructor(private http: HttpClient) {
    this.loadAllSummaryFiles();
  }

  /**
   * Load all summary files from the assets/summaries directory
   */
  private async loadAllSummaryFiles(): Promise<void> {
    this.loadingSubject.next(true);
    this.errorSubject.next(null);

    try {
      const summaryFiles = await this.discoverSummaryFiles();

      if (summaryFiles.length === 0) {
        throw new Error('The manifest lists no summaries');
      }

      const loadRequests = summaryFiles.map(fileInfo =>
        this.loadSingleSummaryFile(fileInfo)
      );

      const results = await forkJoin(loadRequests).toPromise();
      const validDocuments = (results ?? []).filter(
        (doc): doc is ParliamentaryDocument => doc !== null
      );

      if (validDocuments.length === 0) {
        throw new Error('No summary file could be read');
      }

      validDocuments.sort((a, b) => b.date.getTime() - a.date.getTime());
      this.documentsSubject.next(validDocuments);
      this.initializeEnhancedFilters(validDocuments);

      const failed = summaryFiles.length - validDocuments.length;
      if (failed > 0) {
        // Some summaries loaded; say so rather than pretending all is well.
        this.errorSubject.next(
          `${failed} van de ${summaryFiles.length} samenvattingen konden niet worden geladen.`
        );
      }
    } catch (error) {
      // Never substitute placeholder content here. These are summaries of real
      // debates attributed to real parties, and invented stand-ins are
      // indistinguishable from the real thing once the notice disappears.
      console.error('Error loading summary files:', error);
      this.documentsSubject.next([]);
      this.errorSubject.next(
        'De samenvattingen konden niet worden geladen. Probeer het opnieuw.'
      );
    } finally {
      this.loadingSubject.next(false);
    }
  }

  /**
   * List the available summary files.
   *
   * A browser cannot enumerate a directory, so the build publishes
   * assets/summaries/manifest.json (written by deploy_summaries.py) and that is
   * the only source of truth.
   */
  private async discoverSummaryFiles(): Promise<SummaryFileInfo[]> {
    const manifest = await this.http
      .get<{ files: string[]; count: number; generated: string }>(
        'assets/summaries/manifest.json'
      )
      .toPromise();

    if (!manifest?.files?.length) {
      throw new Error('manifest.json is empty or missing a files array');
    }

    return this.parseFileNames(manifest.files);
  }

  /**
   * Parse filenames to extract model and ID information
   */
  private parseFileNames(filenames: string[]): SummaryFileInfo[] {
    return filenames
      .filter(filename => filename.endsWith('.json'))
      .map(filename => {
        // Parse pattern: {MODEL}_summary_{ID}.json or {MODEL}_{ID}.json
        const match = filename.match(/^(.+?)(?:_summary)?_([a-f0-9\-]{36})\.json$/);
        if (match) {
          return {
            filename,
            model: match[1],
            id: match[2]
          };
        }
        // Fallback: treat as unknown pattern but still try to load
        return {
          filename,
          model: 'unknown',
          id: filename.replace('.json', '')
        };
      })
      .filter(info => info.id !== 'unknown'); // Only include properly parsed files
  }

  /**
   * Load a single summary file
   */
  private loadSingleSummaryFile(fileInfo: SummaryFileInfo): Observable<ParliamentaryDocument | null> {
    const url = `assets/summaries/${fileInfo.filename}`;
    
    return this.http.get<ParliamentarySummary>(url).pipe(
      map(summary => {
        if (!summary || !summary.meeting_info) {
          console.warn(`Invalid summary structure in ${fileInfo.filename}`);
          return null;
        }

        const document: ParliamentaryDocument = {
          id: summary.meeting_info.verslag_id || fileInfo.id,
          title: summary.meeting_info.vergadering_titel || `Meeting ${fileInfo.id}`,
          date: new Date(summary.meeting_info.vergadering_datum || Date.now()),
          summary: {
            ...summary,
            processing_info: {
              ...summary.processing_info,
              ai_model: summary.processing_info.ai_model || fileInfo.model
            }
          }
        };

        console.log(`Loaded: ${document.title} (${fileInfo.model})`);
        return document;
      }),
      catchError(error => {
        console.error(`Failed to load ${fileInfo.filename}:`, error);
        return of(null);
      })
    );
  }

  /**
   * Create manifest.json helper method
   * Call this method to generate a manifest of your files
   */
  public generateManifestCode(filenames: string[]): string {
    const manifest = JSON.stringify(filenames, null, 2);
    return `Create this file at /assets/summaries/manifest.json:\n\n${manifest}`;
  }
  private initializeEnhancedFilters(documents: ParliamentaryDocument[]): void {
    // Extract unique topics with counts
    const topicCounts = new Map<string, number>();
    const partyCounts = new Map<string, number>();

    documents.forEach(doc => {
      doc.summary.main_topics.forEach(topic => {
        topicCounts.set(topic.topic, (topicCounts.get(topic.topic) || 0) + 1);
        
        normalizePartyPositions(topic.party_positions).forEach(({ party }) => {
          partyCounts.set(party, (partyCounts.get(party) || 0) + 1);
        });
      });
    });

    // Create enhanced topic filters
    const topicFilters: TopicFilter[] = Array.from(topicCounts.entries()).map(([topic, count]) => ({
      name: topic,
      selected: true,
      count: count
    }));

    // Create enhanced party filters with colors and counts
    const partyColors: { [key: string]: string } = {
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
      'Minister': '#666666'
    };

    const partyFilters: PartyFilter[] = Array.from(partyCounts.entries()).map(([party, count]) => ({
      name: party,
      selected: true,
      color: partyColors[party] || '#666666',
      positions: count
    }));

    this.topicFiltersSubject.next(topicFilters);
    this.partyFiltersSubject.next(partyFilters);
  }

  private applyEnhancedFilters(
    documents: ParliamentaryDocument[],
    topicFilters: TopicFilter[],
    partyFilters: PartyFilter[],
    searchFilter: SearchFilter
  ): ParliamentaryDocument[] {
    const selectedTopics = topicFilters.filter(f => f.selected).map(f => f.name);
    const selectedParties = partyFilters.filter(f => f.selected).map(f => f.name);

    return documents.filter(doc => {
      // Apply topic filter
      const hasSelectedTopic = doc.summary.main_topics.some(topic => 
        selectedTopics.includes(topic.topic)
      );

      // Apply party filter
      const hasSelectedParty = doc.summary.main_topics.some(topic =>
        normalizePartyPositions(topic.party_positions).some(({ party }) =>
          selectedParties.includes(party)
        )
      );

      // Apply enhanced search filter
      const matchesSearch = this.matchesEnhancedSearchQuery(doc, searchFilter);

      return hasSelectedTopic && hasSelectedParty && matchesSearch;
    });
  }

  private matchesEnhancedSearchQuery(doc: ParliamentaryDocument, searchFilter: SearchFilter): boolean {
    if (!searchFilter.query.trim()) {
      return true;
    }

    const query = searchFilter.query.toLowerCase();
    const searchableText: string[] = [];

    // Add executive summary
    searchableText.push(doc.summary.executive_summary.toLowerCase());

    // Add topics if enabled
    if (searchFilter.includeTopics) {
      doc.summary.main_topics.forEach(topic => {
        searchableText.push(topic.topic.toLowerCase());
        searchableText.push(topic.summary.toLowerCase());
      });
    }

    // Add context if enabled
    if (searchFilter.includeContext) {
      doc.summary.main_topics.forEach(topic => {
        if (topic.context) {
          Object.values(topic.context).forEach(contextValue => {
            if (contextValue) {
              searchableText.push(contextValue.toLowerCase());
            }
          });
        }
      });
    }

    // Add party positions if enabled
    if (searchFilter.includePositions) {
      doc.summary.main_topics.forEach(topic => {
        normalizePartyPositions(topic.party_positions).forEach(position => {
          searchableText.push(position.mainPosition.toLowerCase());
          position.proposals?.forEach(proposal =>
            searchableText.push(proposal.toLowerCase())
          );
        });
      });
    }

    // Add reasoning if enabled
    if (searchFilter.includeReasoning) {
      doc.summary.main_topics.forEach(topic => {
        normalizePartyPositions(topic.party_positions).forEach(position => {
          if (position.reasoning) {
            searchableText.push(position.reasoning.toLowerCase());
          }
          if (position.evidence) {
            searchableText.push(position.evidence.toLowerCase());
          }
        });
      });
    }

    // Add decisions if enabled
    if (searchFilter.includeDecisions) {
      doc.summary.key_decisions.forEach(decision => {
        searchableText.push(decision.toLowerCase());
      });
    }

    // Add next steps
    if (doc.summary.next_steps) {
      doc.summary.next_steps.forEach(step => {
        searchableText.push(step.toLowerCase());
      });
    }

    return searchableText.some(text => text.includes(query));
  }

  // Public methods for updating filters
  updateTopicFilter(topicName: string, selected: boolean): void {
    const currentFilters = this.topicFiltersSubject.value;
    const updatedFilters = currentFilters.map(filter =>
      filter.name === topicName ? { ...filter, selected } : filter
    );
    this.topicFiltersSubject.next(updatedFilters);
  }

  updatePartyFilter(partyName: string, selected: boolean): void {
    const currentFilters = this.partyFiltersSubject.value;
    const updatedFilters = currentFilters.map(filter =>
      filter.name === partyName ? { ...filter, selected } : filter
    );
    this.partyFiltersSubject.next(updatedFilters);
  }

  updateSearchFilter(searchFilter: Partial<SearchFilter>): void {
    const currentFilter = this.searchFilterSubject.value;
    this.searchFilterSubject.next({ ...currentFilter, ...searchFilter });
  }

  // Method to refresh/reload all files
  public async refreshDocuments(): Promise<void> {
    this.documentsSubject.next([]);
    await this.loadAllSummaryFiles();
  }

  // Get statistics about loaded documents
  public getDocumentStats(): Observable<{
    totalDocuments: number;
    totalTopics: number;
    uniqueParties: number;
    dateRange: { earliest: Date; latest: Date } | null;
    modelBreakdown: { [model: string]: number };
  }> {
    return this.documents$.pipe(
      map(documents => {
        if (documents.length === 0) {
          return {
            totalDocuments: 0,
            totalTopics: 0,
            uniqueParties: 0,
            dateRange: null,
            modelBreakdown: {}
          };
        }

        const totalTopics = documents.reduce((sum, doc) => sum + doc.summary.main_topics.length, 0);
        const allParties = new Set<string>();
        const modelBreakdown: { [model: string]: number } = {};
        
        documents.forEach(doc => {
          // Count parties
          doc.summary.main_topics.forEach(topic => {
            normalizePartyPositions(topic.party_positions).forEach(({ party }) =>
              allParties.add(party)
            );
          });
          
          // Count models
          const model = doc.summary.processing_info.ai_model || 'unknown';
          modelBreakdown[model] = (modelBreakdown[model] || 0) + 1;
        });

        const dates = documents.map(doc => doc.date).sort((a, b) => a.getTime() - b.getTime());
        
        return {
          totalDocuments: documents.length,
          totalTopics,
          uniqueParties: allParties.size,
          dateRange: {
            earliest: dates[0],
            latest: dates[dates.length - 1]
          },
          modelBreakdown
        };
      })
    );
  }
}