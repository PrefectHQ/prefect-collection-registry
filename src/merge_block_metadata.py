import json
from pathlib import Path

if __name__ == "__main__":
    collection_dirs = Path("collections").glob("prefect-*")
    collections = {"collections": {}}
    for collection_dir in sorted(collection_dirs):
        (collection_dir / "blocks").mkdir(exist_ok=True)
        # get the latest tag
        matches = sorted((collection_dir / "blocks").glob("*.json"), reverse=True)
        if matches:
            path = matches[0]
            collections["collections"][collection_dir.stem] = json.loads(
                path.read_text()
            )
    (Path("views") / "aggregate-block-metadata.json").write_text(
        json.dumps(collections, indent=2)
    )
