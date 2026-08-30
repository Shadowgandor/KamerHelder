import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting
} from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';

import { SummaryService } from './summary.service';
import { SummaryIndexEntry } from '../models/parliamentary-summary.model';

const MANIFEST = 'assets/summaries/manifest.json';
const FILE = 'summary_11111111-1111-1111-1111-111111111111.json';
const ID = '11111111-1111-1111-1111-111111111111';

/** Let pending promise continuations run before asserting on requests. */
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

const entry = (over: Partial<SummaryIndexEntry> = {}): SummaryIndexEntry => ({
  file: FILE,
  id: ID,
  title: '1e vergadering',
  date: '2026-02-10T00:00:00+01:00',
  model: 'claude-sonnet-5',
  summaryText: 'Een debat over de zorgpremie.',
  topics: ['Zorgpremie'],
  parties: ['VVD', 'SP'],
  topicCount: 1,
  decisionCount: 2,
  factCheckCount: 1,
  ...over
});

const fullSummary = {
  executive_summary: 'Een debat over de zorgpremie.',
  main_topics: [
    {
      topic: 'Zorgpremie',
      summary: 'Discussie over het eigen risico.',
      party_positions: [{ party: 'VVD', position: 'Voor' }],
      outcome: 'Motie aangenomen'
    }
  ],
  key_decisions: ['Motie aangenomen', 'Amendement verworpen'],
  political_dynamics: '',
  next_steps: [],
  fact_checks: [],
  meeting_info: {
    vergadering_titel: '1e vergadering',
    vergadering_datum: '2026-02-10T00:00:00+01:00',
    verslag_id: ID,
    status: 'GECORRIGEERD'
  },
  processing_info: { processing_date: '2026-02-11T00:00:00Z' }
};

describe('SummaryService', () => {
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(withXhr()), provideHttpClientTesting()]
    });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  /**
   * These are summaries of real debates attributed to real parties. A failure
   * must show nothing rather than placeholder content, which is
   * indistinguishable from the real thing once the notice is dismissed.
   */
  it('shows no documents when the index cannot be loaded', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).error(new ProgressEvent('network error'));
    await settle();

    expect(await firstValueFrom(service.documents$)).toEqual([]);
    expect(await firstValueFrom(service.error$)).toContain(
      'konden niet worden geladen'
    );
  });

  it('shows no documents when the index is empty', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ summaries: [], count: 0, generated: '' });
    await settle();

    expect(await firstValueFrom(service.documents$)).toEqual([]);
    expect(await firstValueFrom(service.error$)).toBeTruthy();
  });

  /**
   * The whole point of the index: the list is complete after one request, so
   * page load does not scale with the number of meetings.
   */
  it('renders the list from the index without fetching any summary', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({
      summaries: [entry()],
      count: 1,
      generated: ''
    });
    await settle();

    const docs = await firstValueFrom(service.documents$);
    expect(docs.length).toBe(1);
    expect(docs[0].title).toBe('1e vergadering');
    expect(docs[0].summary).toBeNull();
    expect(docs[0].index.decisionCount).toBe(2);

    // No request for the summary file itself; http.verify() in afterEach
    // would also fail if one had been issued.
    http.expectNone(`assets/summaries/${FILE}`);
  });

  it('fetches a summary on demand and attaches it', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ summaries: [entry()], count: 1, generated: '' });
    await settle();

    const loading = service.ensureSummaryLoaded(ID);
    await settle();
    http.expectOne(`assets/summaries/${FILE}`).flush(fullSummary);
    await loading;

    const docs = await firstValueFrom(service.documents$);
    expect(docs[0].summary).not.toBeNull();
    expect(docs[0].summary!.main_topics[0].topic).toBe('Zorgpremie');
  });

  it('does not re-fetch a summary it already has', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ summaries: [entry()], count: 1, generated: '' });
    await settle();

    const first = service.ensureSummaryLoaded(ID);
    await settle();
    http.expectOne(`assets/summaries/${FILE}`).flush(fullSummary);
    await first;

    await service.ensureSummaryLoaded(ID);
    await settle();
    http.expectNone(`assets/summaries/${FILE}`);
  });

  it('reports a summary that fails to load and leaves the list intact', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ summaries: [entry()], count: 1, generated: '' });
    await settle();

    const loading = service.ensureSummaryLoaded(ID);
    await settle();
    http.expectOne(`assets/summaries/${FILE}`).error(new ProgressEvent('404'));
    await loading;

    const docs = await firstValueFrom(service.documents$);
    expect(docs.length).toBe(1);
    expect(docs[0].summary).toBeNull();
    expect(await firstValueFrom(service.error$)).toContain('1e vergadering');
  });

  it('searches the index before the full summary is available', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ summaries: [entry()], count: 1, generated: '' });
    await settle();

    service.updateSearchFilter({ query: 'zorgpremie' });
    expect((await firstValueFrom(service.filteredDocuments$)).length).toBe(1);

    service.updateSearchFilter({ query: 'stikstof' });
    expect((await firstValueFrom(service.filteredDocuments$)).length).toBe(0);
  });
});
