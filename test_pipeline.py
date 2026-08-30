"""
Offline tests for the parsing and summarization pipeline.

    python -m unittest test_pipeline -v

No API calls are made; responses are stubbed.
"""

import json
import unittest
from types import SimpleNamespace

import summarizer
from xml_text_extractor import VLOSDocumentParser

NS = "http://www.tweedekamer.nl/ggm/vergaderverslag/v1.0"


def vlos(body: str) -> str:
    return f'<?xml version="1.0"?><vlosCoreDocument xmlns="{NS}">{body}</vlosCoreDocument>'


def turn(naam, fractie, text, chair="false", tag="woordvoerder", inner=""):
    return f"""
      <{tag}>
        <spreker>
          <fractie>{fractie}</fractie><aanhef>De heer</aanhef>
          <verslagnaam>{naam}</verslagnaam><weergavenaam>{naam}</weergavenaam>
          <achternaam>{naam}</achternaam><functie>lid Tweede Kamer</functie>
        </spreker>
        <isvoorzitter>{chair}</isvoorzitter>
        <tekst><alinea><alineaitem>{text}</alineaitem></alinea></tekst>
        {inner}
      </{tag}>"""


class TestVLOSParser(unittest.TestCase):
    def parse(self, body):
        result = VLOSDocumentParser().parse_document(vlos(body))
        self.assertTrue(result["parsed_successfully"], result.get("error"))
        return result

    def test_speaker_is_attributed_with_party(self):
        text = self.parse(turn("Klaver", "GroenLinks-PvdA", "Dit is mijn punt."))[
            "full_text"
        ]
        self.assertIn("**De heer Klaver (GroenLinks-PvdA):**", text)
        self.assertIn("Dit is mijn punt.", text)

    def test_interruption_is_attributed_to_the_interrupter(self):
        """
        Interruptions are nested inside the turn they interrupt. Their text must
        not be absorbed into the surrounding speaker's turn.
        """
        body = turn(
            "Klaver",
            "GroenLinks-PvdA",
            "Ik was aan het woord.",
            inner=turn("Wilders", "PVV", "Dat klopt niet!", tag="interrumpant"),
        )
        text = self.parse(body)["full_text"]

        self.assertIn("**De heer Wilders (PVV) [interruptie]:**", text)
        # The interrupter's words must appear under their own header, after it.
        klaver = text.index("**De heer Klaver")
        wilders = text.index("**De heer Wilders")
        self.assertLess(klaver, wilders)
        self.assertGreater(text.index("Dat klopt niet!"), wilders)

    def test_inline_emphasis_tails_are_kept(self):
        """Text following an inline <nadruk> tag used to be dropped silently."""
        body = """<woordvoerder><spreker><fractie>VVD</fractie>
            <verslagnaam>Yesilgoz</verslagnaam></spreker>
            <isvoorzitter>false</isvoorzitter>
            <tekst><alinea><alineaitem>Wij vinden <nadruk type="Vet">dit</nadruk>
            volstrekt onaanvaardbaar.</alineaitem></alinea></tekst>
            </woordvoerder>"""
        text = self.parse(body)["full_text"]
        self.assertIn("Wij vinden dit volstrekt onaanvaardbaar.", text)

    def test_motions_are_reproduced_verbatim(self):
        motion = """<draadboekfragment soort="Motie indiening"><tekst>
            <alineagroep type="Motietekst">
              <alinea><alineaitem>De Kamer,</alineaitem></alinea>
              <alinea><alineaitem>verzoekt de regering iets te doen,</alineaitem></alinea>
            </alineagroep>
            <alineagroep type="Motieinfo">
              <alinea><alineaitem>Deze motie is voorgesteld door het lid Bontenbal.</alineaitem></alinea>
            </alineagroep></tekst></draadboekfragment>"""
        text = self.parse(turn("Bontenbal", "CDA", "Ik heb een motie.", inner=motion))[
            "full_text"
        ]
        self.assertIn("> MOTIE:", text)
        self.assertIn("> verzoekt de regering iets te doen,", text)
        # Motion metadata is prose, not part of the quoted motion.
        self.assertIn("Deze motie is voorgesteld door het lid Bontenbal.", text)

    def test_chair_is_labelled_by_role_without_duplicate_line(self):
        body = """<woordvoerder><spreker><verslagnaam>Bosma</verslagnaam>
            <functie>voorzitter</functie></spreker>
            <isvoorzitter>true</isvoorzitter>
            <tekst><alinea>
              <alineaitem>De voorzitter:</alineaitem>
              <alineaitem>Ik open de vergadering.</alineaitem>
            </alinea></tekst></woordvoerder>"""
        text = self.parse(body)["full_text"]
        self.assertIn("**De voorzitter:**", text)
        self.assertEqual(text.count("De voorzitter:"), 1)

    def test_roll_call_is_collapsed(self):
        body = """<activiteit soort="Opening"><titel>Opening</titel><tekst><alinea>
            <alineaitem>Aanwezig zijn 138 leden der Kamer, te weten:</alineaitem>
            <alineaitem>Aardema, Beckerman, Ceder, Dijk, Ellian</alineaitem>
            </alinea></tekst></activiteit>"""
        text = self.parse(body)["full_text"]
        self.assertNotIn("Aardema, Beckerman", text)

    def test_malformed_xml_reports_failure(self):
        result = VLOSDocumentParser().parse_document("<not-xml")
        self.assertFalse(result["parsed_successfully"])
        self.assertIn("error", result)


class TestSummarySchema(unittest.TestCase):
    def walk_objects(self, node, path="root"):
        """Yield every object subschema, so each can be checked for strictness."""
        if not isinstance(node, dict):
            return
        if node.get("type") == "object":
            yield path, node
        for key in ("properties", "items"):
            value = node.get(key)
            if isinstance(value, dict):
                if key == "items":
                    yield from self.walk_objects(value, f"{path}[]")
                else:
                    for name, sub in value.items():
                        yield from self.walk_objects(sub, f"{path}.{name}")

    def test_every_object_is_strict(self):
        """
        Structured outputs require additionalProperties:false and every property
        listed in `required`, at every level, or the API rejects the schema.
        """
        for path, obj in self.walk_objects(summarizer.SUMMARY_SCHEMA):
            self.assertIs(
                obj.get("additionalProperties"),
                False,
                f"{path} is missing additionalProperties: false",
            )
            self.assertEqual(
                sorted(obj.get("required", [])),
                sorted(obj.get("properties", {})),
                f"{path} required does not list every property",
            )

    def test_request_is_well_formed(self):
        verslag = {
            "id": "abc",
            "vergadering_titel": "1e vergadering",
            "vergadering_datum": "2026-01-01T00:00:00+01:00",
            "readable_text": "**De heer Klaver (GroenLinks-PvdA):**\nHallo.",
        }
        params = summarizer.build_request(verslag)

        self.assertEqual(params["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(params["thinking"], {"type": "adaptive"})
        self.assertEqual(params["tools"][0]["type"], "web_search_20260209")
        self.assertTrue(params["tools"][0]["allowed_domains"])
        # The transcript is the cached prefix; it is the bulk of every request.
        block = params["messages"][0]["content"][0]
        self.assertEqual(block["cache_control"], {"type": "ephemeral"})
        self.assertIn("Hallo.", block["text"])


class TestExtractSummary(unittest.TestCase):
    def message(self, payload, model="claude-sonnet-5"):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            model=model,
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=14,
                cache_creation_input_tokens=250_000,
                cache_read_input_tokens=3_000_000,
                output_tokens=4_000,
                server_tool_use=SimpleNamespace(web_search_requests=3),
            ),
        )

    def payload(self):
        return {
            "executive_summary": "Samenvatting.",
            "main_topics": [],
            "key_decisions": [],
            "political_dynamics": "",
            "next_steps": [],
            "fact_checks": [],
        }

    def test_metadata_is_attached(self):
        info = {"vergadering_titel": "1e vergadering", "verslag_id": "abc"}
        summary = summarizer.extract_summary(self.message(self.payload()), info, 1234)

        self.assertEqual(summary["meeting_info"], info)
        self.assertEqual(summary["processing_info"]["ai_model"], "claude-sonnet-5")
        self.assertEqual(summary["processing_info"]["web_searches"], 3)
        self.assertEqual(summary["processing_info"]["transcript_chars"], 1234)

    def test_cached_tokens_are_recorded(self):
        """
        The transcript is a cached prefix, so input_tokens alone is misleading:
        the spend sits in the cache write and the search loop's cache reads.
        """
        info = summarizer.extract_summary(self.message(self.payload()), {}, 0)
        proc = info["processing_info"]
        self.assertEqual(proc["cache_creation_input_tokens"], 250_000)
        self.assertEqual(proc["cache_read_input_tokens"], 3_000_000)

    def test_missing_text_block_is_an_error(self):
        message = SimpleNamespace(content=[], model="m", usage=SimpleNamespace())
        with self.assertRaises(ValueError):
            summarizer.extract_summary(message, {}, 0)

    def test_truncated_response_is_rejected(self):
        """A max_tokens cut-off yields invalid JSON; say so rather than crashing."""
        message = self.message(self.payload())
        message.stop_reason = "max_tokens"
        with self.assertRaises(ValueError) as ctx:
            summarizer.extract_summary(message, {}, 0)
        self.assertIn("incomplete", str(ctx.exception))

    def test_web_searches_defaults_to_zero_without_server_tool_use(self):
        message = self.message(self.payload())
        message.usage.server_tool_use = None
        summary = summarizer.extract_summary(message, {}, 0)
        self.assertEqual(summary["processing_info"]["web_searches"], 0)


if __name__ == "__main__":
    unittest.main()
