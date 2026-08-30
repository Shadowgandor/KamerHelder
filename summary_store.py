"""
Where finished summaries live, and how to tell whether one already exists.

Shared by summarizer.py (which decides what to summarize) and
document_processor.py (which decides what to download), so the two cannot
disagree about what is already done.
"""

from pathlib import Path

# Only the deployed copies survive a fresh checkout: root-level summary_*.json
# is gitignored, so on CI the working directory starts empty. Checking only the
# working directory makes every nightly run redo work it already paid for.
DEPLOYED_DIR = Path("parliamentary-summaries/src/assets/summaries")


def summary_filename(verslag_id: str) -> str:
    return f"summary_{verslag_id}.json"


def already_summarized(verslag_id: str) -> bool:
    """True if this verslag has a summary, deployed or freshly written."""
    if not verslag_id:
        return False
    name = summary_filename(verslag_id)
    return (DEPLOYED_DIR / name).exists() or Path(name).exists()
