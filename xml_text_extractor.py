"""
Parses VLOS XML meeting reports into a structured, attributed transcript.

Reads verslagen_with_content.json, writes verslagen_parsed.json with a
`readable_text` field per verslag.

The transcript preserves the structure the VLOS format already encodes:
agenda items become headings, every contribution is attributed to a named
speaker with their fractie, interruptions are marked as such, and motion texts
are reproduced verbatim. Previous versions of this script space-joined every
element's text into a single line, which discarded all of that (and silently
dropped element tails).
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

NS = "{http://www.tweedekamer.nl/ggm/vergaderverslag/v1.0}"

# The opening of every plenary lists all present members and ministers by name,
# spread over several paragraphs. It is ~2000 characters of pure noise for
# summarization, so collapse it up to the next heading or speaker turn.
ROLL_CALL_RE = re.compile(
    r"Aanwezig zijn\s+\d+\s+leden der Kamer,\s*te weten:.*?(?=\n\n(?:#|\*\*)|\Z)",
    re.DOTALL,
)


def local(elem) -> str:
    """Tag name without the VLOS namespace prefix."""
    return elem.tag.replace(NS, "")


def text_of(elem) -> str:
    """
    Full text of an element including the tails of inline children.

    `<alineaitem>Mevrouw <nadruk>Armut</nadruk> (CDA):</alineaitem>` must come
    out as "Mevrouw Armut (CDA):" — reading only `.text` loses " (CDA):".
    """
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


def child_text(elem, tag: str) -> Optional[str]:
    child = elem.find(f"{NS}{tag}")
    if child is None:
        return None
    value = text_of(child)
    return value or None


class VLOSDocumentParser:
    """Turns a VLOS XML document into a structured transcript."""

    def __init__(self):
        self.speakers: Dict[str, str] = {}
        # Recently emitted headings, used to suppress the format's habit of
        # restating the same title at several nesting levels.
        self.recent_headings: List[str] = []

    # ---------------------------------------------------------------- speakers

    def describe_speaker(self, spreker, is_chair: bool) -> str:
        """
        Build a display label like "Mevrouw Armut (CDA)" or
        "Minister Hermans (Volksgezondheid, Welzijn en Sport)".
        """
        if is_chair:
            return "De voorzitter"

        # `verslagnaam` is the form used in the record ("Van Ark"); `weergavenaam`
        # is sorted for indexes ("Ark van") and reads wrong in running text.
        naam = child_text(spreker, "verslagnaam") or child_text(spreker, "achternaam")
        if not naam:
            return "Onbekende spreker"

        aanhef = child_text(spreker, "aanhef")
        fractie = child_text(spreker, "fractie")
        functie = child_text(spreker, "functie")

        # Members of parliament are identified by their party; members of
        # government by their portfolio, which lives in `functie`.
        if fractie:
            qualifier = fractie
        elif functie and functie.lower() != "lid tweede kamer":
            qualifier = functie
        else:
            qualifier = None

        label = f"{aanhef} {naam}".strip() if aanhef else naam
        if qualifier:
            label = f"{label} ({qualifier})"
            self.speakers[naam] = qualifier

        return label

    # ------------------------------------------------------------- text blocks

    def motion_block(self, groep) -> str:
        """Reproduce a motion verbatim — motions are the substance of decisions."""
        lines = [text_of(item) for item in groep.iter(f"{NS}alineaitem")]
        return "> MOTIE:\n> " + "\n> ".join(line for line in lines if line)

    def collect_content(self, node, acc: List[str]) -> None:
        """
        Gather every paragraph and motion under `node`, in document order.

        Paragraph text can sit at any depth — directly under <tekst>, inside an
        <alineagroep>, or nested in a <draadboekfragment> — so this recurses
        rather than looking in specific places.
        """
        tag = local(node)

        # Interruptions are nested inside the interrupted speaker's turn. Stop
        # here so their words are attributed to the interrupter, not absorbed
        # into the surrounding turn; the walker renders them separately.
        if tag in ("woordvoerder", "interrumpant") and node is not self.turn_root:
            return

        if tag == "alineagroep" and node.get("type") == "Motietekst":
            block = self.motion_block(node)
            if block.strip("> MOTIE:\n>"):
                acc.append(block)
            return

        if tag == "alinea":
            for item in node.iter(f"{NS}alineaitem"):
                value = text_of(item)
                if value:
                    acc.append(value)
            return

        for child in node:
            self.collect_content(child, acc)

    def nested_turns(self, node):
        """Yield the nearest speaker-turn descendants of `node`."""
        for child in node:
            if local(child) in ("woordvoerder", "interrumpant"):
                yield child
            else:
                yield from self.nested_turns(child)

    def render_turn(self, container) -> List[str]:
        """Render one <woordvoerder> or <interrumpant> block."""
        spreker = container.find(f"{NS}spreker")
        if spreker is None:
            return []

        is_chair = (child_text(container, "isvoorzitter") or "").lower() == "true"
        label = self.describe_speaker(spreker, is_chair)

        lines: List[str] = []
        self.turn_root = container
        self.collect_content(container, lines)
        self.turn_root = None

        # VLOS repeats the speaker label as the first paragraph of each turn
        # ("Mevrouw Armut (CDA):"). We emit our own header, so drop the copy.
        surname = (child_text(spreker, "verslagnaam") or "").split()[-1:]
        surname = surname[0].lower() if surname else ""

        def is_label(line: str) -> bool:
            if not line.endswith(":") or len(line) > 60:
                return False
            lowered = line.lower()
            # The chair's turns are labelled by role rather than by name.
            return lowered == "de voorzitter:" or (surname and surname in lowered)

        while lines and is_label(lines[0]):
            lines = lines[1:]

        if not lines:
            return []

        if local(container) == "interrumpant":
            label = f"{label} [interruptie]"

        return [f"**{label}:**", *lines]

    # ------------------------------------------------------------------- walk

    def render(self, elem, out: List[str], depth: int = 0) -> None:
        """Walk the document in order, emitting headings and speaker turns."""
        tag = local(elem)

        if tag in ("woordvoerder", "interrumpant"):
            block = self.render_turn(elem)
            if block:
                out.append("\n".join(block))
            # An interruption sits inside the turn it interrupts, so keep
            # descending — but only into the nested turns themselves, since
            # render_turn already consumed everything else at this level.
            for nested in self.nested_turns(elem):
                self.render(nested, out, depth + 1)
            return

        if tag in ("activiteit", "activiteithoofd", "activiteitdeel"):
            # A "Spreekbeurt" section is titled after the speaker it contains,
            # which the turn's own header already states.
            if elem.get("soort") != "Spreekbeurt":
                heading = child_text(elem, "onderwerp") or child_text(elem, "titel")
                if heading and heading not in self.recent_headings:
                    level = "##" if tag == "activiteit" else "###"
                    out.append(f"{level} {heading}")
                    self.recent_headings.append(heading)
                    del self.recent_headings[:-3]

        # Anything reached here is outside a speaker turn (turns return early),
        # so it is narrative — chair announcements, procedural notes, motion
        # outcomes. Collect it and stop descending; the collector is recursive.
        elif tag in ("tekst", "draadboekfragment"):
            content: List[str] = []
            self.collect_content(elem, content)
            out.extend(p for p in content if p not in self.recent_headings)
            return

        for child in elem:
            self.render(child, out, depth + 1)

    # ------------------------------------------------------------------ public

    def parse_document(self, xml_content: str) -> Dict:
        try:
            xml_content = xml_content.lstrip("﻿")
            start = xml_content.find("<?xml")
            if start > 0:
                xml_content = xml_content[start:]

            root = ET.fromstring(xml_content)
            self.speakers = {}
            self.recent_headings = []

            vergadering = root.find(f"{NS}vergadering")
            meeting = {}
            if vergadering is not None:
                meeting = {
                    "soort": vergadering.get("soort"),
                    "kamer": vergadering.get("kamer"),
                    "titel": child_text(vergadering, "titel"),
                    "vergaderjaar": child_text(vergadering, "vergaderjaar"),
                    "vergaderingnummer": child_text(vergadering, "vergaderingnummer"),
                    "datum": child_text(vergadering, "datum"),
                }
                meeting = {k: v for k, v in meeting.items() if v}

            out: List[str] = []
            self.render(vergadering if vergadering is not None else root, out)

            full_text = "\n\n".join(block for block in out if block.strip())
            full_text = ROLL_CALL_RE.sub(
                "Aanwezig zijn de leden der Kamer.", full_text
            )

            agenda = [
                child_text(a, "onderwerp") or child_text(a, "titel")
                for a in root.iter(f"{NS}activiteit")
            ]
            agenda = [a for a in agenda if a]

            return {
                "vergadering_info": meeting,
                "agendapunten": agenda,
                "sprekers": self.speakers,
                "full_text": full_text,
                "text_length": len(full_text),
                "num_agendapunten": len(agenda),
                "num_sprekers": len(self.speakers),
                "parsed_successfully": True,
            }

        except ET.ParseError as e:
            return {"error": f"XML parsing error: {e}", "parsed_successfully": False}
        except Exception as e:
            return {"error": f"General parsing error: {e}", "parsed_successfully": False}


def process_verslagen_with_xml_parsing():
    print("=== Processing VLOS XML Documents ===")

    try:
        with open("verslagen_with_content.json", "r", encoding="utf-8") as f:
            verslagen = json.load(f)
    except FileNotFoundError:
        print("No verslagen_with_content.json found. Run document_processor.py first.")
        return

    parser = VLOSDocumentParser()
    processed = []

    for i, verslag in enumerate(verslagen, 1):
        title = verslag.get("vergadering_titel", "Unknown")
        print(f"\n--- {i}/{len(verslagen)}: {title} ---")

        if not (verslag.get("content_extracted") and verslag.get("document_text")):
            print("  No content to parse")
            verslag["summary_ready"] = False
            processed.append(verslag)
            continue

        parsed = parser.parse_document(verslag["document_text"])

        if parsed.get("parsed_successfully"):
            verslag["parsed_content"] = parsed
            verslag["readable_text"] = parsed["full_text"]
            verslag["summary_ready"] = True
            print(
                f"  Parsed: {parsed['text_length']:,} chars, "
                f"{parsed['num_agendapunten']} agenda items, "
                f"{parsed['num_sprekers']} speakers"
            )
        else:
            print(f"  Failed: {parsed.get('error', 'unknown error')}")
            verslag["summary_ready"] = False

        processed.append(verslag)

    with open("verslagen_parsed.json", "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)

    successful = sum(1 for v in processed if v.get("summary_ready"))
    print(f"\n=== Done: {successful}/{len(processed)} ready for summarization ===")
    print("Saved to verslagen_parsed.json")


if __name__ == "__main__":
    process_verslagen_with_xml_parsing()
