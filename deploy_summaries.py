"""
Copies summary JSON files to the Angular assets directory and generates manifest.json.

Usage:
    python deploy_summaries.py
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ASSETS_DIR = Path("parliamentary-summaries/src/assets/summaries")
PATTERN = "summary_*.json"


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    summary_files = sorted(Path(".").glob(PATTERN))

    copied = []
    for src in summary_files:
        shutil.copy2(src, ASSETS_DIR / src.name)
        copied.append(src.name)
        print(f"  Copied: {src.name}")

    # The manifest lists everything in the assets directory, not just what this
    # run copied, so the app still sees summaries from previous runs.
    all_files = sorted(f.name for f in ASSETS_DIR.glob(PATTERN))
    if not all_files:
        print("No summaries found. Run the pipeline first.")
        return

    manifest = {
        "files": all_files,
        "count": len(all_files),
        "generated": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = ASSETS_DIR / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"\nCopied {len(copied)} new file(s); manifest lists {len(all_files)}.")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()
