import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNoopAnimations } from '@angular/platform-browser/animations';

import { AppComponent } from './app.component';
import {
  createProcessedDocument,
  normalizePartyPositions,
  ParliamentaryDocument,
  SummaryIndexEntry
} from './models/parliamentary-summary.model';

describe('AppComponent', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [AppComponent],
      providers: [
        provideHttpClient(withXhr()),
        provideHttpClientTesting(),
        provideNoopAnimations()
      ]
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(AppComponent);
    expect(fixture.componentInstance).toBeTruthy();
  });

  it('renders the application name in the toolbar', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.toolbar-title')?.textContent).toContain(
      'KamerHelder'
    );
  });

  it('labels every fact-check verdict in Dutch', () => {
    const app = TestBed.createComponent(AppComponent).componentInstance;
    expect(app.assessmentLabel('onjuist')).toBe('Onjuist');
    expect(app.assessmentLabel('grotendeels_juist')).toBe('Grotendeels juist');
    expect(app.assessmentLabel('onverifieerbaar')).toBe('Niet te verifiëren');
  });

  it('shows a source link by domain, and falls back to the raw value', () => {
    const app = TestBed.createComponent(AppComponent).componentInstance;
    expect(app.sourceLabel('https://www.rijksoverheid.nl/documenten/x')).toBe(
      'rijksoverheid.nl'
    );
    expect(app.sourceLabel('niet-een-url')).toBe('niet-een-url');
  });
});

describe('normalizePartyPositions', () => {
  it('reads the current array shape', () => {
    const positions = normalizePartyPositions([
      { party: 'VVD', position: 'Voor' },
      { party: 'SP', position: 'Tegen' }
    ]);

    expect(positions.map(p => p.party)).toEqual(['VVD', 'SP']);
    expect(positions[0].mainPosition).toBe('Voor');
  });

  it('still reads the object shape used by older summaries', () => {
    const positions = normalizePartyPositions({
      VVD: 'Voor',
      SP: { position: 'Tegen', reasoning: 'Te duur' }
    });

    expect(positions.map(p => p.party)).toEqual(['VVD', 'SP']);
    expect(positions[0].mainPosition).toBe('Voor');
    expect(positions[1].mainPosition).toBe('Tegen');
    expect(positions[1].reasoning).toBe('Te duur');
  });

  it('treats a missing value as no positions', () => {
    expect(normalizePartyPositions(undefined)).toEqual([]);
  });
});

describe('createProcessedDocument', () => {
  const index: SummaryIndexEntry = {
    file: 'summary_abc.json',
    id: 'abc',
    title: '1e vergadering',
    date: '2026-02-10T00:00:00Z',
    model: 'claude-sonnet-5',
    summaryText: 'Samenvatting.',
    topics: [],
    parties: ['VVD'],
    topicCount: 0,
    decisionCount: 1,
    factCheckCount: 0
  };

  const base: ParliamentaryDocument = {
    id: 'abc',
    title: '1e vergadering',
    date: new Date('2026-02-10T00:00:00Z'),
    index,
    summary: {
      executive_summary: 'Samenvatting.',
      main_topics: [],
      key_decisions: ['Motie aangenomen'],
      political_dynamics: '',
      next_steps: [],
      meeting_info: {
        vergadering_titel: '1e vergadering',
        vergadering_datum: '2026-02-10',
        verslag_id: 'abc',
        status: 'Ongecorrigeerd'
      },
      processing_info: { processing_date: '2026-02-11T00:00:00Z' }
    }
  };

  it('takes its counts from the index', () => {
    const doc = createProcessedDocument(
      { ...base, index: { ...index, factCheckCount: 1 } },
      d => d.toISOString()
    );

    expect(doc.factCheckCount).toBe(1);
    expect(doc.hasFactChecks).toBeTrue();
    expect(doc.hasDecisions).toBeTrue();
  });

  it('handles a meeting with no fact checks', () => {
    const doc = createProcessedDocument(base, d => d.toISOString());
    expect(doc.factCheckCount).toBe(0);
    expect(doc.hasFactChecks).toBeFalse();
  });

  /**
   * The list renders from the index before the full summary arrives, so a
   * document with summary: null must still produce a complete list row.
   */
  it('renders a list row before the full summary has loaded', () => {
    const doc = createProcessedDocument(
      { ...base, summary: null },
      d => d.toISOString()
    );

    expect(doc.summary).toBeNull();
    expect(doc.title).toBe('1e vergadering');
    expect(doc.decisionCount).toBe(1);
    expect(doc.preview).toBe('Samenvatting.');
    expect(doc.nextStepsCount).toBe(0);
  });
});
