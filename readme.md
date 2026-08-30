# KamerHelder

Leesbare samenvattingen van Tweede Kamerdebatten, met een feitencheck.

KamerHelder haalt plenaire verslagen op uit de open data van de Tweede Kamer,
zet ze om in een doorzoekbaar transcript, laat Claude er een Nederlandstalige
samenvatting van maken, controleert de verifieerbare beweringen tegen officiële
bronnen, en publiceert het resultaat als een Angular-webapp.

## Hoe het werkt

```
tk_data_retriever.py   haalt verslagen op uit de Tweede Kamer API
        ↓  plenaire_verslagen.json
document_processor.py  downloadt de documenten en haalt de tekst eruit
        ↓               (alleen wat nog geen samenvatting heeft; met cache)
        ↓  verslagen_with_content.json
xml_text_extractor.py  zet VLOS-XML om in een transcript met sprekers,
        ↓               interrupties en letterlijke moties
        ↓  verslagen_parsed.json
summarizer.py          één verzoek per debat: samenvatting + feitencheck
        ↓  summary_<verslag_id>.json
deploy_summaries.py    kopieert ze naar de Angular-assets + manifest.json
```

Alleen nieuwe verslagen worden verwerkt: heeft een verslag al een
samenvatting, dan wordt het document niet opnieuw opgehaald of geparsed. Op
een dag zonder nieuwe debatten doet de pijplijn dus niets, en dat is geen
fout.

Een debat beslaat 120.000 tot 370.000 tokens. Dat past in één verzoek, dus het
hele debat gaat in één keer naar het model: geen chunking, geen samenvoegstap
die nuance verliest.

De feitencheck gebruikt websearch, beperkt tot officiële domeinen
(rijksoverheid.nl, wetten.overheid.nl, cbs.nl, cpb.nl, en verwante bronnen).
Een bevinding zonder vindbare bron wordt niet opgenomen.

## Aan de slag

Python 3.10 of hoger is nodig voor de `anthropic` 1.x SDK.

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export ANTHROPIC_API_KEY='...'
```

De hele pijplijn draaien:

```bash
python run_pipeline.py            # ophalen, parsen, batch inplannen
python summarizer.py --mode collect   # zodra de batch klaar is
python deploy_summaries.py
```

Samenvatten loopt standaard via de Batch API: de helft goedkoper, maar
asynchroon (meestal binnen een uur, uiterlijk 24 uur). Direct resultaat nodig?

```bash
python run_pipeline.py --summarize sync
```

De webapp draaien:

```bash
cd parliamentary-summaries
npm install
npm start                         # http://localhost:4200
```

## Instellingen

| Variabele | Standaard | Betekenis |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | vereist |
| `KAMERHELDER_MODEL` | `claude-sonnet-5` | `claude-opus-5` geeft scherpere analyse tegen hogere kosten |
| `KAMERHELDER_EFFORT` | `high` | lager betekent minder denk-tokens en lagere kosten |
| `KAMERHELDER_MAX_SEARCHES` | `12` | maximum aantal zoekopdrachten per debat |

Kosten per debat liggen rond $0,45 met Sonnet 5 via de Batch API, en rond
$1,15 zonder batching. Websearch wordt apart afgerekend per zoekopdracht.

## Tests

```bash
python -m unittest test_pipeline -v                                # pijplijn
cd parliamentary-summaries && npm test -- --watch=false --browsers=ChromeHeadless
```

Er worden geen API-verzoeken gedaan in de tests.

## Automatisering

`.github/workflows/nightly.yml` draait elke nacht: verslagen ophalen, de batch
van gisteren ophalen, een nieuwe batch inplannen, en de site opnieuw
publiceren naar GitHub Pages. Omdat batches asynchroon zijn, verschijnt een
samenvatting een dag na het debat.

## Licentie

MIT — zie [LICENSE](LICENSE).
