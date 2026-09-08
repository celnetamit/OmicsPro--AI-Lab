#!/usr/bin/env python3
"""Install the locked curated gene set collection.

The collection, its identifier space and the background rule are frozen in
``LOCKED_METHODS['pathway_enrichment']``. This script converts the official GMT
into the internal JSON form the enrichment step reads. It does not choose a
collection: substituting a different one is a method change and therefore a
versioned code change.

Usage:
    python scripts/fetch_gene_sets.py path/to/h.all.v2023.2.Hs.symbols.gmt

Download the GMT from https://www.gsea-msigdb.org/gsea/msigdb/ (registration
required; redistribution terms prevent bundling it in this repository).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.constants import LOCKED_METHODS  # noqa: E402
from app.settings import settings  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2

    method = LOCKED_METHODS["pathway_enrichment"]
    source = sys.argv[1]
    expected = method["database"].split()[-1]
    if expected not in os.path.basename(source):
        print(
            f"Refusing to install '{os.path.basename(source)}': the locked "
            f"collection is {method['database']} in {method['gene_id_space']} "
            f"identifiers. Installing a different collection would make the "
            f"method version recorded on every run untrue."
        )
        return 1

    gene_sets = {}
    with open(source) as handle:
        for line in handle:
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 3:
                continue
            gene_sets[fields[0]] = fields[2:]

    target_dir = os.path.join(settings.data_dir, "gene_sets")
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, "hallmark.json")
    with open(target, "w") as handle:
        json.dump(gene_sets, handle)

    print(f"Installed {len(gene_sets)} gene sets to {target}")
    print(f"Identifier space: {method['gene_id_space']}")
    print(f"Background rule:  {method['background_rule']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
