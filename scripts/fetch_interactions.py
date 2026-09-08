#!/usr/bin/env python3
"""Install the locked curated ligand-receptor interaction database.

The communication statistic is computed in the validated pipeline; this curated
database is the external asset it reads, and which interactions it contains
defines what the module can and cannot find. Substituting a different database
is a method change and therefore a versioned code change, not an operator
choice.

Usage:
    python scripts/fetch_interactions.py path/to/interaction_input.csv

Download the release named in ``LOCKED_METHODS['cell_communication']['database']``
from https://www.cellphonedb.org/ (its licence prevents bundling it here). The
file must carry a ligand/partner_a column and a receptor/partner_b column of
HGNC symbols.
"""

import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.constants import LOCKED_METHODS  # noqa: E402
from app.settings import settings  # noqa: E402

LIGAND_COLUMNS = ("ligand", "partner_a", "gene_a", "source")
RECEPTOR_COLUMNS = ("receptor", "partner_b", "gene_b", "target")


def _column(header, candidates):
    for candidate in candidates:
        if candidate in header:
            return candidate
    return None


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    method = LOCKED_METHODS["cell_communication"]
    with open(sys.argv[1], newline="") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        ligand_column = _column(header, LIGAND_COLUMNS)
        receptor_column = _column(header, RECEPTOR_COLUMNS)
        if not ligand_column or not receptor_column:
            print(
                "Could not find a ligand column and a receptor column. Expected "
                f"one of {LIGAND_COLUMNS} and one of {RECEPTOR_COLUMNS}."
            )
            return 1

        pairs, seen = [], set()
        for row in reader:
            ligand = (row.get(ligand_column) or "").strip()
            receptor = (row.get(receptor_column) or "").strip()
            if not ligand or not receptor or (ligand, receptor) in seen:
                continue
            seen.add((ligand, receptor))
            pairs.append({"ligand": ligand, "receptor": receptor})

    if not pairs:
        print("No usable ligand-receptor pairs were found in that file.")
        return 1

    target_dir = os.path.join(settings.data_dir, "interactions")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "ligand_receptor.json")
    with open(target, "w") as handle:
        json.dump(pairs, handle)

    print(f"Installed {len(pairs)} ligand-receptor pairs to {target}")
    print(f"Locked database:  {method['database']}")
    print(f"Identifier space: {method['gene_id_space']}")
    print(f"Statistic:        {method['method']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
