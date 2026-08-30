"""
Copies summary JSON files to the Angular assets directory and generates an index.

Usage:
    python deploy_summaries.py

The index (manifest.json) carries enough metadata for the app to render the
meeting list, filter it and search it from a single request. Full summaries are
fetched only when a meeting is opened. Inlining the searchable body text here
instead would make the index as large as the summaries themselves, which
defeats the point — measured at ~1.1 MB versus ~138 KB for 150 meetings.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ASSETS_DIR = Path("parliamentary-summaries/src/assets/summaries")
PATTERN = "summary_*.json"


def positions_of(topic: Dict) -> List[Dict]:
    """Party positions come in two shapes; older summaries use a keyed object."""
    positions = topic.get("party_positions")
    if isinstance(positions, list):
        return positions
    if isinstance(positions, dict):
        return [{"party": name} for name in positions]
    return []


def index_entry(path: Path) -> Dict:
    summary = json.loads(path.read_text(encoding="utf-8"))
    meeting = summary.get("meeting_info", {})
    topics = summary.get("main_topics", [])

    parties = sorted(
        {
            entry.get("party", "")
            for topic in topics
            for entry in positions_of(topic)
            if entry.get("party")
        }
    )

    return {
        "file": path.name,
        "id": meeting.get("verslag_id") or path.stem.removeprefix("summary_"),
        "title": meeting.get("vergadering_titel") or path.stem,
        "date": meeting.get("vergadering_datum") or "",
        "model": summary.get("processing_info", {}).get("ai_model", ""),
        # The executive summary doubles as the list preview and the searchable
        # body; it is short enough (~600 chars) to carry for every meeting.
        "summaryText": summary.get("executive_summary", ""),
        "topics": [t.get("topic", "") for t in topics if t.get("topic")],
        "parties": parties,
        "topicCount": len(topics),
        "decisionCount": len(summary.get("key_decisions", [])),
        "factCheckCount": len(summary.get("fact_checks", [])),
    }


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    for src in sorted(Path(".").glob(PATTERN)):
        shutil.copy2(src, ASSETS_DIR / src.name)
        print(f"  Copied: {src.name}")

    # Index everything in the assets directory, not just what this run copied,
    # so summaries from previous runs stay visible.
    deployed = sorted(ASSETS_DIR.glob(PATTERN))
    if not deployed:
        print("No summaries found. Run the pipeline first.")
        return

    entries = []
    for path in deployed:
        try:
            entries.append(index_entry(path))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"  Skipping unreadable {path.name}: {e}")

    entries.sort(key=lambda e: e["date"], reverse=True)

    manifest = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "count": len(entries),
        # Retained so a cached older build of the app keeps working.
        "files": [e["file"] for e in entries],
        "summaries": entries,
    }
    manifest_path = ASSETS_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    size_kb = manifest_path.stat().st_size / 1024
    print(f"\nIndexed {len(entries)} summaries -> {manifest_path} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
