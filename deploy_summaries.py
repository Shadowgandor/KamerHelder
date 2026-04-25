"""
Copies summary JSON files to the Angular assets directory and generates manifest.json.

Usage:
    python deploy_summaries.py
"""

import json
import shutil
from datetime import datetime
from pathlib import Path

ASSETS_DIR = Path("parliamentary-summaries/src/assets/summaries")
PATTERNS = ["summary_*.json", "deepseek_summary_*.json"]


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    summary_files = []
    for pattern in PATTERNS:
        summary_files.extend(Path(".").glob(pattern))

    if not summary_files:
        print("No summary files found. Run the pipeline first.")
        return

    copied = []
    for src in summary_files:
        dst = ASSETS_DIR / src.name
        shutil.copy2(src, dst)
        copied.append(src.name)
        print(f"  Copied: {src.name}")

    all_files = sorted(f.name for pattern in PATTERNS for f in ASSETS_DIR.glob(pattern))
    manifest = {
        "files": all_files,
        "count": len(all_files),
        "generated": datetime.now().isoformat(),
    }
    manifest_path = ASSETS_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))

    print(f"\nDeployed {len(copied)} file(s) to {ASSETS_DIR}")
    print(f"Manifest written to {manifest_path}")
    print("\nStart the Angular app with:")
    print("  cd parliamentary-summaries && npm start")


if __name__ == "__main__":
    main()
