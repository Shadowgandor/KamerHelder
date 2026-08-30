"""
Summarizes Dutch parliamentary debates and fact-checks their verifiable claims.

Reads verslagen_parsed.json, writes summary_<verslag_id>.json.

Each debate is summarized in a single request. Transcripts run 150k-430k tokens,
which fits comfortably in the 1M-token context window, so there is no chunking:
the model sees the whole debate at once and can follow an argument across the
whole day. Fact-checking happens in the same pass, with web search restricted to
official Dutch government and statistics domains so a flagged claim is backed by
a retrievable source rather than model recall.

Three modes:

    --mode submit    queue every pending debate as a Batch API job (50% cheaper)
    --mode collect   fetch a finished batch and write the summary files
    --mode sync      summarize immediately, without batching

Batches usually finish within the hour but are allowed up to 24, so the nightly
workflow submits one run and collects it the next.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import anthropic

# Summaries that have been deployed are the ones that survive in git; the
# working directory is empty on a fresh CI checkout.
DEPLOYED_DIR = Path("parliamentary-summaries/src/assets/summaries")
BATCH_STATE = Path("batch_state.json")

MODEL = os.getenv("KAMERHELDER_MODEL", "claude-sonnet-5")
EFFORT = os.getenv("KAMERHELDER_EFFORT", "high")
MAX_SEARCHES = int(os.getenv("KAMERHELDER_MAX_SEARCHES", "12"))
MAX_TOKENS = 32000

# Fact-checking is only meaningful against authoritative sources. Restricting the
# search keeps a flagged claim traceable to an official document and caps how far
# the model can wander (web search bills per search).
FACT_CHECK_DOMAINS = [
    "rijksoverheid.nl",
    "tweedekamer.nl",
    "eerstekamer.nl",
    "wetten.overheid.nl",
    "officielebekendmakingen.nl",
    "denederlandsebank.nl",
    "cbs.nl",
    "cpb.nl",
    "scp.nl",
    "rivm.nl",
    "rekenkamer.nl",
    "raadvanstate.nl",
    "europa.eu",
]

SYSTEM_PROMPT = """\
Je bent een parlementair redacteur. Je vat verslagen van de Tweede Kamer samen \
voor geïnteresseerde burgers zonder politieke voorkennis.

Schrijf altijd in het Nederlands, in heldere en neutrale taal. Vermijd \
vakjargon; leg parlementaire termen kort uit waar ze onvermijdelijk zijn. \
Neem geen eigen politiek oordeel op: beschrijf wat partijen vinden en waarom, \
niet wie gelijk heeft.

Het verslag is opgebouwd uit sprekersbeurten. Elke beurt begint met de naam en \
fractie van de spreker, bijvoorbeeld "**Mevrouw Armut (CDA):**". Beurten met \
"[interruptie]" zijn onderbrekingen van een andere spreker. Blokken die \
beginnen met "> MOTIE:" zijn letterlijke moties.

Vat samen op het niveau van onderwerpen, niet van sprekersbeurten. Groepeer \
wat bij elkaar hoort, ook als het verspreid over de dag aan de orde kwam, en \
noem per onderwerp wat de belangrijkste fracties vinden en welk resultaat er \
uit kwam. Baseer key_decisions op de moties en de conclusies van de \
voorzitter.

FEITENCHECK

Controleer feitelijke beweringen die verifieerbaar zijn: cijfers, bedragen, \
data, wetsartikelen, bevoegdheden van instanties, en verwijzingen naar \
bestaande afspraken of rapporten. Gebruik daarvoor het zoekgereedschap. Zoek \
gericht en spaarzaam: alleen voor beweringen die er inhoudelijk toe doen en \
die je daadwerkelijk kunt natrekken.

Neem een bewering alleen op in fact_checks als je een bron hebt gevonden die \
er direct iets over zegt. Vermeld die bron als URL. Zonder bron geen \
fact_check-item.

Controleer NIET: meningen, politieke oordelen, voorspellingen over de \
toekomst, retorische overdrijving, of uitspraken waarbij de spreker zelf \
aangeeft te schatten ("ongeveer", "uit mijn hoofd").

Een lege fact_checks-lijst is een prima uitkomst en komt vaak voor. Het doel \
is een klein aantal goed onderbouwde bevindingen, niet een lange lijst.\
"""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {
            "type": "string",
            "description": "Drie tot vijf zinnen over de kern van de vergadering.",
        },
        "main_topics": {
            "type": "array",
            "description": "De inhoudelijke onderwerpen, belangrijkste eerst.",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "summary": {"type": "string"},
                    "party_positions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "party": {
                                    "type": "string",
                                    "description": "Fractie, of bewindspersoon met functie.",
                                },
                                "position": {"type": "string"},
                            },
                            "required": ["party", "position"],
                            "additionalProperties": False,
                        },
                    },
                    "outcome": {
                        "type": "string",
                        "description": "Uitkomst of vervolgstap; leeg als die er niet was.",
                    },
                },
                "required": ["topic", "summary", "party_positions", "outcome"],
                "additionalProperties": False,
            },
        },
        "key_decisions": {"type": "array", "items": {"type": "string"}},
        "political_dynamics": {
            "type": "string",
            "description": "Verhoudingen: samenwerking, conflict, coalitie versus oppositie.",
        },
        "next_steps": {"type": "array", "items": {"type": "string"}},
        "fact_checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "speaker": {"type": "string"},
                    "assessment": {
                        "type": "string",
                        "enum": [
                            "onjuist",
                            "misleidend",
                            "grotendeels_juist",
                            "onverifieerbaar",
                        ],
                    },
                    "explanation": {"type": "string"},
                    "correction": {
                        "type": "string",
                        "description": "De juiste informatie; leeg als niet van toepassing.",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs van geraadpleegde bronnen.",
                    },
                },
                "required": [
                    "claim",
                    "speaker",
                    "assessment",
                    "explanation",
                    "correction",
                    "sources",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "executive_summary",
        "main_topics",
        "key_decisions",
        "political_dynamics",
        "next_steps",
        "fact_checks",
    ],
    "additionalProperties": False,
}


def meeting_info(verslag: Dict) -> Dict:
    return {
        "vergadering_titel": verslag.get("vergadering_titel"),
        "vergadering_datum": verslag.get("vergadering_datum"),
        "verslag_id": verslag.get("id"),
        "status": verslag.get("status"),
    }


def build_request(verslag: Dict) -> Dict:
    """Build the Messages API parameters for one debate."""
    info = meeting_info(verslag)
    header = (
        f"Vergadering: {info.get('vergadering_titel') or 'onbekend'}\n"
        f"Datum: {info.get('vergadering_datum') or 'onbekend'}\n\n"
        "Hieronder staat het volledige verslag.\n\n"
    )

    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": SYSTEM_PROMPT,
        "thinking": {"type": "adaptive"},
        "output_config": {
            "effort": EFFORT,
            "format": {"type": "json_schema", "schema": SUMMARY_SCHEMA},
        },
        "tools": [
            {
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": MAX_SEARCHES,
                "allowed_domains": FACT_CHECK_DOMAINS,
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": header + verslag["readable_text"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    }


def extract_summary(
    message, info: Dict, transcript_chars: int, usage_note: str = ""
) -> Dict:
    """Turn an API response into the summary document we persist."""
    if getattr(message, "stop_reason", None) == "max_tokens":
        # Structured output guarantees valid JSON only if the response finished;
        # a truncated one fails to parse with a confusing error otherwise.
        raise ValueError(
            f"response hit the {MAX_TOKENS}-token cap and is incomplete"
        )

    text = next((b.text for b in message.content if b.type == "text"), None)
    if not text:
        raise ValueError("no text block in response")

    summary = json.loads(text)
    summary["meeting_info"] = info
    summary["processing_info"] = {
        "ai_model": message.model,
        "processing_date": datetime.now(timezone.utc).isoformat(),
        "input_tokens": message.usage.input_tokens,
        "output_tokens": message.usage.output_tokens,
        "web_searches": getattr(
            getattr(message.usage, "server_tool_use", None), "web_search_requests", 0
        )
        or 0,
        "transcript_chars": transcript_chars,
    }
    if usage_note:
        summary["processing_info"]["note"] = usage_note
    return summary


def output_path(verslag_id: str) -> Path:
    return Path(f"summary_{verslag_id}.json")


def write_summary(summary: Dict, verslag_id: str) -> Path:
    path = output_path(verslag_id)
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def already_summarized(verslag_id: str) -> bool:
    name = f"summary_{verslag_id}.json"
    return (DEPLOYED_DIR / name).exists() or Path(name).exists()


def load_pending(limit: Optional[int] = None, only: Optional[str] = None) -> List[Dict]:
    """
    Debates that are parsed, not yet summarized, and have usable text.

    `only` selects one debate by verslag id and ignores whether it already has a
    summary, so a single meeting can be re-run after a prompt or model change.
    """
    try:
        with open("verslagen_parsed.json", encoding="utf-8") as f:
            verslagen = json.load(f)
    except FileNotFoundError:
        print("verslagen_parsed.json not found. Run xml_text_extractor.py first.")
        sys.exit(1)

    usable = [
        v for v in verslagen if v.get("summary_ready") and v.get("readable_text")
    ]

    if only:
        selected = [v for v in usable if v.get("id") == only]
        if not selected:
            print(f"No parsed debate with id {only}.")
            sys.exit(1)
        return selected

    pending = [v for v in usable if not already_summarized(v.get("id", ""))]
    pending.sort(key=lambda v: v.get("vergadering_datum") or "")
    return pending[:limit] if limit else pending


# --------------------------------------------------------------------- sync


def run_sync(client, verslag: Dict) -> Dict:
    """
    Summarize one debate synchronously.

    Streams because the input is large and `max_tokens` is high; a non-streaming
    request of this size risks hitting the HTTP timeout. Server-side web search
    can return `pause_turn` when a turn runs long, which means the turn is
    unfinished — resend it to continue rather than accepting a truncated answer.
    """
    params = build_request(verslag)
    messages = list(params["messages"])

    for attempt in range(4):
        with client.messages.stream(**{**params, "messages": messages}) as stream:
            message = stream.get_final_message()

        if message.stop_reason != "pause_turn":
            return extract_summary(
                message, meeting_info(verslag), len(verslag["readable_text"])
            )

        messages = messages + [{"role": "assistant", "content": message.content}]
        print(f"    turn paused, continuing ({attempt + 1})")

    raise RuntimeError("turn still paused after 4 continuations")


# -------------------------------------------------------------------- batch


def submit_batch(client, pending: List[Dict]) -> None:
    if BATCH_STATE.exists():
        # Normal in the nightly workflow when the previous batch has not
        # finished yet. Skipping is correct: those debates are already queued,
        # and resubmitting them would pay for the same work twice.
        state = json.loads(BATCH_STATE.read_text())
        print(
            f"Batch {state['batch_id']} (submitted {state['submitted']}) is still "
            "pending; not queueing another. Run --mode collect once it finishes."
        )
        return

    requests = [
        {"custom_id": f"verslag_{v['id']}", "params": build_request(v)}
        for v in pending
    ]

    batch = client.messages.batches.create(requests=requests)

    # Everything collect() needs is recorded here, so a later run can write the
    # summaries without the transcripts still being present — the nightly fetch
    # window moves on, and a debate submitted yesterday may have aged out of it.
    BATCH_STATE.write_text(
        json.dumps(
            {
                "batch_id": batch.id,
                "submitted": datetime.now(timezone.utc).isoformat(),
                "model": MODEL,
                "verslagen": {
                    f"verslag_{v['id']}": {
                        "verslag_id": v["id"],
                        "meeting_info": meeting_info(v),
                        "transcript_chars": len(v["readable_text"]),
                    }
                    for v in pending
                },
            },
            indent=2,
            ensure_ascii=False,
        )
    )

    print(f"Submitted batch {batch.id} with {len(requests)} debate(s).")
    print(f"State written to {BATCH_STATE}. Collect it with --mode collect.")


def collect_batch(client) -> None:
    if not BATCH_STATE.exists():
        print("No pending batch. Nothing to collect.")
        return

    state = json.loads(BATCH_STATE.read_text())
    batch_id = state["batch_id"]
    batch = client.messages.batches.retrieve(batch_id)

    if batch.processing_status != "ended":
        counts = batch.request_counts
        print(
            f"Batch {batch_id} is still {batch.processing_status} "
            f"({counts.processing} processing, {counts.succeeded} done). "
            "Leaving state in place; try again later."
        )
        return

    # Transcripts are only needed to continue a paused turn, which is rare, so
    # load them lazily rather than requiring them for a normal collect.
    transcripts: Optional[Dict[str, Dict]] = None

    succeeded = failed = paused = 0

    for result in client.messages.batches.results(batch_id):
        entry = state["verslagen"].get(result.custom_id)
        if entry is None:
            print(f"  {result.custom_id}: not in batch state, skipped")
            failed += 1
            continue

        verslag_id = entry["verslag_id"]
        info = entry["meeting_info"]
        title = info.get("vergadering_titel") or verslag_id

        if result.result.type != "succeeded":
            print(f"  {title}: {result.result.type}")
            failed += 1
            continue

        message = result.result.message

        try:
            if message.stop_reason == "pause_turn":
                # The batch worker stopped mid-turn. Finish it synchronously —
                # this is rare and the remaining work is small.
                if transcripts is None:
                    transcripts = load_transcripts()
                verslag = transcripts.get(verslag_id)
                if verslag is None:
                    raise ValueError(
                        "turn paused but the transcript is no longer available"
                    )
                print(f"  {title}: turn paused, finishing synchronously")
                summary = finish_paused(client, verslag, message)
                paused += 1
            else:
                summary = extract_summary(message, info, entry["transcript_chars"])
        except (json.JSONDecodeError, ValueError, RuntimeError) as e:
            print(f"  {title}: unusable response ({e})")
            failed += 1
            continue

        path = write_summary(summary, verslag_id)
        print(f"  {title} -> {path}")
        succeeded += 1

    BATCH_STATE.unlink()
    print(
        f"\nCollected {succeeded} summary/summaries"
        + (f" ({paused} needed continuation)" if paused else "")
        + (f", {failed} failed" if failed else "")
        + "."
    )


def load_transcripts() -> Dict[str, Dict]:
    try:
        with open("verslagen_parsed.json", encoding="utf-8") as f:
            return {v.get("id"): v for v in json.load(f)}
    except FileNotFoundError:
        return {}


def finish_paused(client, verslag: Dict, message) -> Dict:
    params = build_request(verslag)
    messages = params["messages"] + [{"role": "assistant", "content": message.content}]

    for _ in range(4):
        with client.messages.stream(**{**params, "messages": messages}) as stream:
            message = stream.get_final_message()
        if message.stop_reason != "pause_turn":
            return extract_summary(
                message,
                meeting_info(verslag),
                len(verslag["readable_text"]),
                usage_note="continued after pause",
            )
        messages = messages + [{"role": "assistant", "content": message.content}]

    raise RuntimeError("turn still paused after 4 continuations")


# --------------------------------------------------------------------- main


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument(
        "--mode",
        choices=["submit", "collect", "sync"],
        default="submit",
        help="submit/collect use the Batch API (50%% cheaper); sync runs now",
    )
    parser.add_argument(
        "--limit", type=int, help="only process this many pending debates"
    )
    parser.add_argument(
        "--only",
        metavar="VERSLAG_ID",
        help="re-run one debate by id, even if it already has a summary",
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.")
        sys.exit(1)

    client = anthropic.Anthropic()

    if args.mode == "collect":
        collect_batch(client)
        return

    pending = load_pending(args.limit, args.only)
    if not pending:
        print("Every parsed debate already has a summary.")
        return

    print(f"{len(pending)} debate(s) to summarize with {MODEL}:")
    for v in pending:
        chars = len(v.get("readable_text", ""))
        print(f"  {v.get('vergadering_datum', '?')[:10]}  "
              f"{v.get('vergadering_titel', 'onbekend')}  ({chars:,} chars)")

    if args.mode == "submit":
        submit_batch(client, pending)
        return

    succeeded = failed = 0
    for i, verslag in enumerate(pending, 1):
        title = verslag.get("vergadering_titel", "onbekend")
        print(f"\n[{i}/{len(pending)}] {title}")
        try:
            summary = run_sync(client, verslag)
        except KeyboardInterrupt:
            print("\nInterrupted. Completed summaries are saved; rerun to continue.")
            return
        except Exception as e:
            print(f"    failed: {type(e).__name__}: {e}")
            failed += 1
            continue

        path = write_summary(summary, verslag["id"])
        info = summary["processing_info"]
        print(
            f"    -> {path} ({len(summary['main_topics'])} onderwerpen, "
            f"{len(summary['fact_checks'])} feitenchecks, "
            f"{info['web_searches']} zoekopdrachten)"
        )
        succeeded += 1

    print(f"\nDone: {succeeded} summarized" + (f", {failed} failed" if failed else "."))


if __name__ == "__main__":
    main()
