"""
Pipeline runner: fetches, processes, and summarizes Tweede Kamer parliamentary data.

Usage:
    python run_pipeline.py                  # Full pipeline with DeepSeek
    python run_pipeline.py --summarizer claude
    python run_pipeline.py --start-from document_processor
    python run_pipeline.py --days 60 --max-items 150
"""

import argparse
import subprocess
import sys
import os
import json
from pathlib import Path


STEPS = [
    "tk_data_retriever",
    "document_processor",
    "xml_text_extractor",
    "summarizer",
]

STEP_OUTPUTS = {
    "tk_data_retriever": "plenaire_verslagen.json",
    "document_processor": "verslagen_with_content.json",
    "xml_text_extractor": "verslagen_parsed.json",
}


def run_script(script: str, extra_env: dict = None, extra_args: list = None):
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, f"{script}.py"] + (extra_args or [])
    result = subprocess.run(cmd, env=env)
    if result.returncode != 0:
        print(f"\nStep '{script}' failed with exit code {result.returncode}. Aborting.")
        sys.exit(result.returncode)


def check_prerequisite(filename: str, step: str):
    if not Path(filename).exists():
        print(f"Required file '{filename}' not found. Run '{step}.py' first.")
        sys.exit(1)
    with open(filename) as f:
        data = json.load(f)
    if not data:
        print(f"'{filename}' is empty. The previous step may have produced no results.")
        sys.exit(1)
    print(f"  Found {len(data)} items in {filename}")


def main():
    parser = argparse.ArgumentParser(description="Run the KamerHelder pipeline")
    parser.add_argument(
        "--summarizer",
        choices=["claude", "deepseek"],
        default="deepseek",
        help="LLM to use for summarization (default: deepseek)",
    )
    parser.add_argument(
        "--start-from",
        choices=STEPS,
        default="tk_data_retriever",
        help="Skip earlier steps and start from this step",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Number of days to look back for verslagen (default: 30)",
    )
    parser.add_argument(
        "--max-items",
        type=int,
        default=100,
        help="Maximum number of verslagen to fetch (default: 100)",
    )
    args = parser.parse_args()

    start_index = STEPS.index(args.start_from)

    print("=== KamerHelder Pipeline ===\n")

    if start_index == 0:
        print("Step 1/4: Fetching parliamentary data...")
        run_script("tk_data_retriever", extra_args=["--days", str(args.days), "--max-items", str(args.max_items)])
        check_prerequisite("plenaire_verslagen.json", "tk_data_retriever")
    else:
        print("Step 1/4: Skipping (--start-from)")

    if start_index <= 1:
        print("\nStep 2/4: Downloading and extracting document text...")
        check_prerequisite("plenaire_verslagen.json", "tk_data_retriever")
        run_script("document_processor")
        check_prerequisite("verslagen_with_content.json", "document_processor")
    else:
        print("Step 2/4: Skipping (--start-from)")

    if start_index <= 2:
        print("\nStep 3/4: Parsing XML documents...")
        check_prerequisite("verslagen_with_content.json", "document_processor")
        run_script("xml_text_extractor")
        check_prerequisite("verslagen_parsed.json", "xml_text_extractor")
    else:
        print("Step 3/4: Skipping (--start-from)")

    if start_index <= 3:
        print(f"\nStep 4/4: Summarizing with {args.summarizer}...")
        check_prerequisite("verslagen_parsed.json", "xml_text_extractor")

        if args.summarizer == "claude":
            if not os.getenv("ANTHROPIC_API_KEY"):
                print("ANTHROPIC_API_KEY environment variable is not set.")
                sys.exit(1)
            run_script("claude_summarizer")
        else:
            if not os.getenv("DEEPSEEK_API_KEY"):
                print("DEEPSEEK_API_KEY environment variable is not set.")
                sys.exit(1)
            run_script("deepseek_summarizer")

    print("\n=== Pipeline complete! ===")
    summaries = list(Path(".").glob("*summary_*.json"))
    print(f"Generated {len(summaries)} summary file(s).")
    print("\nNext step: deploy summaries to the Angular app:")
    print("  python deploy_summaries.py")


if __name__ == "__main__":
    main()
