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
  SummaryIndexEntry,
  normalizePartyPositions
} from '../models/parliamentary-summary.model';

@Injectable({
  providedIn: 'root'
})
export class SummaryService {
  private documentsSubject = new BehaviorSubject<ParliamentaryDocument[]>([]);
  private topicFiltersSubject = new BehaviorSubject<TopicFilter[]>([]);
  private partyFiltersSubject = new BehaviorSubject<PartyFilter[]>([]);
  private loadingSubject = new BehaviorSubject<boolean>(false);
  private errorSubject = new BehaviorSubject<string | null>(null);
  /** In-flight summary fetches, keyed by meeting id. */
  private pendingSummaries = new Map<string, Promise<ParliamentarySummary | null>>();

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
   * Load the index and render from it.
   *
   * The index (manifest.json) describes every meeting in one request: title,
   * date, topics, parties and counts. Full summaries are ~9.5 KB each and are
   * fetched only when a meeting is opened, so the list appears immediately
   * however many meetings there are.
   */
  private async loadAllSummaryFiles(): Promise<void> {
    this.loadingSubject.next(true);
    this.errorSubject.next(null);

    try {
      const entries = await this.loadIndex();

      if (entries.length === 0) {
        throw new Error('The index lists no summaries');
      }

      const documents: ParliamentaryDocument[] = entries.map(entry => ({
        id: entry.id,
        title: entry.title,
        date: new Date(entry.date || Date.now()),
        index: entry,
        summary: null
      }));

      documents.sort((a, b) => b.date.getTime() - a.date.getTime());
      this.documentsSubject.next(documents);
      this.initializeEnhancedFilters(documents);
    } catch (error) {
      // Never substitute placeholder content here. These are summaries of real
      // debates attributed to real parties, and invented stand-ins are
      // indistinguishable from the real thing once the notice disappears.
      console.error('Error loading the summary index:', error);
      this.documentsSubject.next([]);
      this.errorSubject.next(
        'De samenvattingen konden niet worden geladen. Probeer het opnieuw.'
      );
    } finally {
      this.loadingSubject.next(false);
    }
  }

  /**
   * A browser cannot enumerate a directory, so the build publishes
   * assets/summaries/manifest.json (written by deploy_summaries.py) and that is
   * the only source of truth.
   */
  private async loadIndex(): Promise<SummaryIndexEntry[]> {
    const manifest = await this.http
      .get<{ summaries?: SummaryIndexEntry[]; count: number; generated: string }>(
        'assets/summaries/manifest.json'
      )
      .toPromise();

    if (!manifest?.summaries?.length) {
      throw new Error('manifest.json is empty or has no summaries array');
    }

    return manifest.summaries;
  }

  /**
   * Fetch one meeting's full summary, unless it is already loaded.
   *
   * Concurrent requests for the same meeting share a single fetch, so
   * re-selecting a meeting costs nothing.
   */
  async ensureSummaryLoaded(id: string): Promise<void> {
    const doc = this.documentsSubject.value.find(d => d.id === id);

    if (!doc || doc.summary) {
      return;
    }

    let request = this.pendingSummaries.get(id);
    if (!request) {
      request = this.fetchSummary(doc.index);
      this.pendingSummaries.set(id, request);
    }

    const summary = await request;
    this.pendingSummaries.delete(id);

    if (!summary) {
      this.errorSubject.next(
        `De samenvatting van "${doc.title}" kon niet worden geladen.`
      );
      return;
    }

    this.documentsSubject.next(
      this.documentsSubject.value.map(d => (d.id === id ? { ...d, summary } : d))
    );
  }

  private fetchSummary(
    entry: SummaryIndexEntry
  ): Promise<ParliamentarySummary | null> {
    return this.http
      .get<ParliamentarySummary>(`assets/summaries/${entry.file}`)
      .pipe(
        catchError(error => {
          console.error(`Failed to load ${entry.file}:`, error);
          return of(null);
        })
      )
      .toPromise()
      .then(summary => summary ?? null);
  }


  private initializeEnhancedFilters(documents: ParliamentaryDocument[]): void {
    // Extract unique topics with counts
    const topicCounts = new Map<string, number>();
    const partyCounts = new Map<string, number>();

    documents.forEach(doc => {
      doc.index.topics.forEach(topic =>
        topicCounts.set(topic, (topicCounts.get(topic) || 0) + 1)
      );
      doc.index.parties.forEach(party =>
        partyCounts.set(party, (partyCounts.get(party) || 0) + 1)
      );
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
      // Topic and party filters read the index, so they work before a
      // meeting's full summary has been fetched.
      const hasSelectedTopic = doc.index.topics.some(topic =>
        selectedTopics.includes(topic)
      );
      const hasSelectedParty = doc.index.parties.some(party =>
        selectedParties.includes(party)
      );

      // Apply enhanced search filter
      const matchesSearch = this.matchesEnhancedSearchQuery(doc, searchFilter);

      return hasSelectedTopic && hasSelectedParty && matchesSearch;
    });
  }

  /**
   * Match a meeting against the search box.
   *
   * Title, topics, parties and the executive summary come from the index and
   * are always searchable. The deeper fields — party positions, decisions,
   * next steps — only exist once the full summary has been fetched, so they
   * are searched opportunistically rather than triggering a download of every
   * summary on the first keystroke.
   */
  private matchesEnhancedSearchQuery(
    doc: ParliamentaryDocument,
    searchFilter: SearchFilter
  ): boolean {
    const query = searchFilter.query.trim().toLowerCase();
    if (!query) {
      return true;
    }

    const haystack: string[] = [
      doc.index.title,
      doc.index.summaryText,
      ...doc.index.topics,
      ...doc.index.parties
    ];

    const summary = doc.summary;
    if (summary) {
      summary.main_topics.forEach(topic => {
        haystack.push(topic.topic, topic.summary, topic.outcome);
        normalizePartyPositions(topic.party_positions).forEach(position => {
          haystack.push(position.party, position.mainPosition);
          if (position.reasoning) haystack.push(position.reasoning);
          if (position.evidence) haystack.push(position.evidence);
          position.proposals?.forEach(proposal => haystack.push(proposal));
        });
        if (topic.context) {
          Object.values(topic.context).forEach(value => {
            if (value) haystack.push(value);
          });
        }
      });
      haystack.push(...summary.key_decisions, ...summary.next_steps);
      summary.fact_checks?.forEach(fc =>
        haystack.push(fc.claim, fc.speaker, fc.explanation, fc.correction)
      );
    }

    return haystack.join(' ').toLowerCase().includes(query);
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

        // Stats read the index so the toolbar shows real totals immediately,
        // without waiting for every summary to be fetched.
        const totalTopics = documents.reduce(
          (sum, doc) => sum + doc.index.topicCount,
          0
        );
        const allParties = new Set<string>();
        const modelBreakdown: { [model: string]: number } = {};

        documents.forEach(doc => {
          doc.index.parties.forEach(party => allParties.add(party));
          const model = doc.index.model || 'unknown';
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