"""Regenerate the four fictional supplier PDFs in sample_proposals/."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfp_eval.proposals import generate_sample_proposals


def main() -> None:
    destination = ROOT / "sample_proposals"
    for path in generate_sample_proposals(destination):
        print(path)


if __name__ == "__main__":
    main()
