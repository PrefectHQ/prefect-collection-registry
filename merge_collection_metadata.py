import json
from pathlib import Path

if __name__ == "__main__":
    collection_dirs = Path("collections").glob("prefect-*")
    collections = {"collections": {}}
    for collection_dir in sorted(collection_dirs):
        # get the latest tag
        path = sorted(collection_dir.glob("*"), reverse=True)[0]
        collections["collections"][collection_dir.stem] = json.loads(path.read_text())
    (Path("collections") / "collection_blocks_data.json").write_text(
        json.dumps(collections, indent=2)
    )
