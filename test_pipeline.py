"""
Offline tests for the parsing and summarization pipeline.

    python -m unittest test_pipeline -v

No API calls are made; responses are stubbed.
"""

import json
import os
from datetime import datetime, timedelta, timezone
import pathlib
import shutil
import tempfile
import unittest
from types import SimpleNamespace

import summarizer
import summary_store
import tk_data_retriever
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


class TestVersionPreference(unittest.TestCase):
    """
    When several versions of one meeting exist, the pipeline must summarize the
    best one. "GECORRIGEERD" is a substring of "ONGECORRIGEERD", so the earlier
    containment test scored both the same and the corrected-transcript
    preference silently never applied.
    """

    def score(self, soort, status):
        return tk_data_retriever._version_score(
            {"soort": f"VerslagSoort.{soort}", "status": f"VerslagStatus.{status}"}
        )

    def test_corrected_beats_uncorrected(self):
        self.assertGreater(
            self.score("EINDPUBLICATIE", "GECORRIGEERD"),
            self.score("EINDPUBLICATIE", "ONGECORRIGEERD"),
        )

    def test_final_publication_outranks_correction_status(self):
        # An uncorrected final publication still beats a corrected interim one.
        self.assertGreater(
            self.score("EINDPUBLICATIE", "ONGECORRIGEERD"),
            self.score("TUSSENPUBLICATIE", "GECORRIGEERD"),
        )

    def test_unknown_values_score_zero(self):
        self.assertEqual(tk_data_retriever._version_score({}), 0)
        self.assertEqual(self.score("ONBEKEND", "ONBEKEND"), 0)

    def test_enum_name_takes_the_final_segment(self):
        self.assertEqual(
            tk_data_retriever._enum_name("VerslagStatus.ONGECORRIGEERD"),
            "ONGECORRIGEERD",
        )
        self.assertEqual(tk_data_retriever._enum_name(None), "")

    def test_deduplication_keeps_the_corrected_version(self):
        retriever = tk_data_retriever.TweedeKamerDataRetriever.__new__(
            tk_data_retriever.TweedeKamerDataRetriever
        )
        group = [
            {
                "id": "uncorrected",
                "vergadering_id": "v1",
                "soort": "VerslagSoort.EINDPUBLICATIE",
                "status": "VerslagStatus.ONGECORRIGEERD",
            },
            {
                "id": "corrected",
                "vergadering_id": "v1",
                "soort": "VerslagSoort.EINDPUBLICATIE",
                "status": "VerslagStatus.GECORRIGEERD",
            },
        ]
        kept = retriever._deduplicate_verslagen(group)
        self.assertEqual([v["id"] for v in kept], ["corrected"])

        # Order must not decide the outcome.
        kept_reversed = retriever._deduplicate_verslagen(list(reversed(group)))
        self.assertEqual([v["id"] for v in kept_reversed], ["corrected"])


class TestBatchStaleness(unittest.TestCase):
    """
    The nightly run skips submission while a batch is pending. If a batch never
    finishes, that skip is correct but silent, and the site quietly stops
    updating — so a batch past its 24-hour cap has to be reported as an error.
    """

    def setUp(self):
        self.now = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

    def submitted(self, hours_ago):
        return (self.now - timedelta(hours=hours_ago)).isoformat()

    def test_a_fresh_batch_is_not_stale(self):
        self.assertFalse(summarizer.batch_is_stale(self.submitted(2), self.now))

    def test_a_batch_within_the_cap_is_not_stale(self):
        self.assertFalse(summarizer.batch_is_stale(self.submitted(23), self.now))

    def test_a_batch_past_the_cap_is_stale(self):
        self.assertTrue(summarizer.batch_is_stale(self.submitted(30), self.now))

    def test_age_is_reported_in_hours(self):
        self.assertAlmostEqual(
            summarizer.batch_age_hours(self.submitted(5), self.now), 5.0
        )


class TestSummaryStore(unittest.TestCase):
    """
    The skip check decides both what gets summarized and what gets downloaded,
    so it has to look where summaries actually survive. Root-level
    summary_*.json is gitignored; only the deployed copies exist on a fresh CI
    checkout, and checking the working directory alone made every nightly run
    redo the whole window.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cwd = os.getcwd()
        os.chdir(self.tmp)
        self.deployed = pathlib.Path(summary_store.DEPLOYED_DIR)
        self.deployed.mkdir(parents=True)

    def tearDown(self):
        os.chdir(self.cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_finds_a_deployed_summary(self):
        (self.deployed / "summary_abc.json").write_text("{}")
        self.assertTrue(summary_store.already_summarized("abc"))

    def test_finds_a_freshly_written_summary(self):
        pathlib.Path("summary_def.json").write_text("{}")
        self.assertTrue(summary_store.already_summarized("def"))

    def test_absent_summary_is_not_claimed(self):
        self.assertFalse(summary_store.already_summarized("ghi"))

    def test_blank_id_is_not_summarized(self):
        self.assertFalse(summary_store.already_summarized(""))

    def test_summarizer_and_processor_share_one_definition(self):
        # Two copies of this rule drifting apart would mean downloading
        # documents nobody needs, or skipping ones that were never summarized.
        import document_processor

        self.assertIs(summarizer.already_summarized, summary_store.already_summarized)
        self.assertIs(
            document_processor.already_summarized, summary_store.already_summarized
        )


if __name__ == "__main__":
    unittest.main()
