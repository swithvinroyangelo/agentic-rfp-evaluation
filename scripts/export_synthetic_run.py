"""Write the committed sample JSON from an offline fake-model run."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfp_eval.sample_export import build_synthetic_export


def main() -> None:
    destination = ROOT / "sample_output" / "synthetic_rfp_run.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        payload = build_synthetic_export(Path(folder) / "synthetic.db", ROOT / "sample_proposals")
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(destination)


if __name__ == "__main__":
    main()
