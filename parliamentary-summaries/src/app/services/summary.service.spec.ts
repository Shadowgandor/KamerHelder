import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting
} from '@angular/common/http/testing';
import { firstValueFrom } from 'rxjs';

import { SummaryService } from './summary.service';

const MANIFEST = 'assets/summaries/manifest.json';

/** Let pending promise continuations run before asserting on requests. */
const settle = () => new Promise(resolve => setTimeout(resolve, 0));

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
  it('shows no documents when the manifest cannot be loaded', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).error(new ProgressEvent('network error'));

    await settle();

    expect(await firstValueFrom(service.documents$)).toEqual([]);
    expect(await firstValueFrom(service.error$)).toContain(
      'konden niet worden geladen'
    );
  });

  it('shows no documents when the manifest is empty', async () => {
    const service = TestBed.inject(SummaryService);
    http.expectOne(MANIFEST).flush({ files: [], count: 0, generated: '' });

    await settle();

    expect(await firstValueFrom(service.documents$)).toEqual([]);
    expect(await firstValueFrom(service.error$)).toBeTruthy();
  });

  it('loads the summaries listed in the manifest', async () => {
    const service = TestBed.inject(SummaryService);
    const file = 'summary_11111111-1111-1111-1111-111111111111.json';
    http.expectOne(MANIFEST).flush({ files: [file], count: 1, generated: '' });
    await settle();

    http.expectOne(`assets/summaries/${file}`).flush({
      executive_summary: 'Samenvatting.',
      main_topics: [],
      key_decisions: [],
      political_dynamics: '',
      next_steps: [],
      meeting_info: {
        vergadering_titel: '1e vergadering',
        vergadering_datum: '2026-02-10T00:00:00+01:00',
        verslag_id: '11111111-1111-1111-1111-111111111111',
        status: 'GECORRIGEERD'
      },
      processing_info: { processing_date: '2026-02-11T00:00:00Z' }
    });

    await settle();

    const docs = await firstValueFrom(service.documents$);
    expect(docs.length).toBe(1);
    expect(docs[0].title).toBe('1e vergadering');
    expect(await firstValueFrom(service.error$)).toBeNull();
  });

  it('reports partial failure but keeps the summaries that did load', async () => {
    const service = TestBed.inject(SummaryService);
    const ok = 'summary_11111111-1111-1111-1111-111111111111.json';
    const bad = 'summary_22222222-2222-2222-2222-222222222222.json';
    http.expectOne(MANIFEST).flush({ files: [ok, bad], count: 2, generated: '' });
    await settle();

    http.expectOne(`assets/summaries/${ok}`).flush({
      executive_summary: 'Samenvatting.',
      main_topics: [],
      key_decisions: [],
      political_dynamics: '',
      next_steps: [],
      meeting_info: {
        vergadering_titel: '1e vergadering',
        vergadering_datum: '2026-02-10T00:00:00+01:00',
        verslag_id: '11111111-1111-1111-1111-111111111111',
        status: 'GECORRIGEERD'
      },
      processing_info: { processing_date: '2026-02-11T00:00:00Z' }
    });
    http.expectOne(`assets/summaries/${bad}`).error(new ProgressEvent('404'));

    await settle();

    expect((await firstValueFrom(service.documents$)).length).toBe(1);
    expect(await firstValueFrom(service.error$)).toContain('1 van de 2');
  });
});
