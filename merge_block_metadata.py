import json
from pathlib import Path

if __name__ == "__main__":
    blocks_dirs = Path("blocks").glob("prefect*")
    collections = {"blocks": {}}
    for block_dir in sorted(blocks_dirs):
        # get the latest tag
        path = sorted(block_dir.glob("*"), reverse=True)[0]
        collections["blocks"][block_dir.stem] = json.loads(path.read_text())
    (Path("views") / "aggregate-block-metadata.json").write_text(
        json.dumps(collections, indent=2)
    )
