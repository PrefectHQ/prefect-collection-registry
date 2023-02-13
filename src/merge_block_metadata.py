import json
from pathlib import Path

from generate_block_metadata import BLOCKS_BLACKLIST, generate_block_metadata


def generate_prefect_block_metadata():
    """Generates block metadata from the prefect package."""
    from prefect.blocks.core import Block
    from prefect.utilities.dispatch import get_registry_for_type

    block_registry = get_registry_for_type(Block) or {}

    return {
        "block_types": dict(
            sorted(
                {
                    block_subcls.get_block_type_slug(): generate_block_metadata(
                        block_subcls
                    )
                    for block_subcls in block_registry.values()
                    if block_subcls.get_block_type_slug() not in BLOCKS_BLACKLIST
                }.items()
            )
        )
    }


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
