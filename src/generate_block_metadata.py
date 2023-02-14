import importlib
import inspect
import json
import logging
from abc import ABC
from importlib.metadata import entry_points
from pathlib import Path
from sys import argv
from types import ModuleType
from typing import Any, Dict, List, Type
from uuid import uuid4

from prefect import flow
from prefect.blocks.core import Block
from prefect.plugins import safe_load_entrypoints

import utils

# Some collection blocks share names with core blocks. We exclude them
# from the registry for now to avoid confusion.
BLOCKS_BLACKLIST = {"k8s-job"}


def generate_block_metadata(block_subcls: Type[Block]) -> Dict[str, Any]:
    """
    Takes a block subclass and returns a JSON dict representation of
    its corresponding block type and block schema.
    """
    block_type_dict = block_subcls._to_block_type().dict(
        exclude={"id", "created", "updated", "is_protected"}, json_compatible=True
    )
    block_type_dict["block_schema"] = block_subcls._to_block_schema(
        block_type_id=uuid4()
    ).dict(
        exclude={"id", "created", "updated", "block_type_id", "block_type"},
        json_compatible=True,
    )

    # make it deterministic to prevent false positives of changes
    block_type_dict["block_schema"]["capabilities"] = sorted(
        block_type_dict["block_schema"]["capabilities"]
    )
    return block_type_dict


def generate_block_metadata_for_module(module: ModuleType):
    block_subclasses = discover_block_subclasses(module)
    return dict(
        sorted(
            {
                block_subcls.get_block_type_slug(): generate_block_metadata(
                    block_subcls
                )
                for block_subcls in block_subclasses
                if block_subcls.get_block_type_slug() not in BLOCKS_BLACKLIST
            }.items()
        )
    )


def discover_block_subclasses(module: ModuleType) -> List[Type[Block]]:
    return [
        cls
        for _, cls in inspect.getmembers(module)
        if Block.is_block_class(cls)
        and cls.__name__ != "Block"
        and ABC not in getattr(cls, "__bases__", [])
    ]


def generate_block_metadata_for_collection(collection_name: str):
    # group is only available for Python 3.10+
    collections = safe_load_entrypoints(entry_points(group="prefect.collections"))
    output_dict = {}
    for ep_name, module in collections.items():
        if isinstance(module, Exception):
            logging.warning(f"Error loading collection entrypoint {ep_name} - skipping")
            continue
        discovered_collection_name = module.__name__.split(".")[0].replace("_", "-")
        if collection_name != discovered_collection_name:
            continue

        output_dict["block_types"] = {
            **output_dict.get("block_types", {}),
            **generate_block_metadata_for_module(module),
        }
    return {
        collection_name: output_dict,
    }


def write_block_metadata(collection_metadata: Dict[str, Any], collection_name: str):
    if "_" in collection_name:
        raise ValueError(
            f"Names can only contain dashes, not underscores, got: {collection_name!r}"
        )

    collection_slug = collection_name.replace("-", "_")
    collection_version = importlib.import_module(collection_slug).__version__
    collection_metadata_path = (
        Path("collections") / collection_name / "blocks" / f"{collection_version}.json"
    )
    collection_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(collection_metadata_path, "w") as f:
        json.dump(collection_metadata, f, indent=2)


@flow
def update_block_metadata_for_collection(collection_name: str, branch_name: str):
    block_metadata = generate_block_metadata_for_collection(collection_name)
    utils.submit_updates(
        collection_metadata=block_metadata, branch_name=branch_name, variety="block"
    )


if __name__ == "__main__":
    collection_name = argv[1]
    block_metadata = generate_block_metadata_for_collection(collection_name)
    write_block_metadata(block_metadata, collection_name)
