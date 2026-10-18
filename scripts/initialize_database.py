"""Create the local SQLite database and seed criteria when the table is empty."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rfp_eval.dashboard import default_database_path
from rfp_eval.db import initialize_database


def main() -> None:
    db_path = default_database_path(ROOT)
    initialize_database(db_path)
    print(db_path)


if __name__ == "__main__":
    main()
