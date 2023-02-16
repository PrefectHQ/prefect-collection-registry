import json
from pathlib import Path

from generate_block_metadata import generate_prefect_block_metadata

if __name__ == "__main__":
    collection_dirs = Path("collections").glob("prefect-*")
    collections = {}

    collections["prefect"] = generate_prefect_block_metadata()

    for collection_dir in sorted(collection_dirs):
        # get the latest tag
        matches = sorted((collection_dir / "blocks").glob("*.json"), reverse=True)
        if matches:
            path = matches[0]
            collections[collection_dir.stem] = json.loads(path.read_text())

    collections = dict(sorted(collections.items()))
    (Path("views") / "aggregate-block-metadata.json").write_text(
        json.dumps(collections, indent=2)
    )
