import inspect
import importlib
import json
import logging
from abc import ABC
from importlib.metadata import entry_points
from pathlib import Path
from prefect import flow, task
from sys import argv
from types import ModuleType
from typing import Any, Dict, List, Type
from uuid import uuid4

from prefect.blocks.core import Block
from prefect.plugins import safe_load_entrypoints
from utils import submit_updates, get_collection_names

def generate_block_subcls_metadata(block_subcls: Type[Block]) -> Dict[str, Any]:
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
    return {
        block_subcls.get_block_type_slug(): generate_block_subcls_metadata(block_subcls)
        for block_subcls in block_subclasses
    }


def discover_block_subclasses(module: ModuleType) -> List[Type[Block]]:
    print(f"Discovering block subclasses in {module.__name__}...")

    if module.__name__ == "prefect":
        # special case for core        
        block_submodules = [
            module.blocks.kubernetes,
            module.blocks.notifications,
            module.blocks.system,
        ]
        
        infrastructure_submodules = [
            module.infrastructure.docker,
            module.infrastructure.kubernetes,
            module.infrastructure.process,
        ]
        
        subclasses_for_each_submodule = [
            discover_block_subclasses(submodule)
            for submodule in block_submodules + infrastructure_submodules
        ]
        
        return [subcls for sublist in subclasses_for_each_submodule for subcls in sublist]
        
        
    return [
        cls
        for _, cls in inspect.getmembers(module)
        if Block.is_block_class(cls)
        and cls.__name__ != "Block"
        and ABC not in getattr(cls, "__bases__", [])
    ]


def generate_all_block_metadata(collection_name: str) -> Dict[str, Any]:
    # group is only available for Python 3.10+
    collections = safe_load_entrypoints(entry_points(group="prefect.collections"))
    collections_plus_core = {
        "prefect": importlib.import_module("prefect"),
        **collections,
    }
    
    output_dict = {}
    for ep_name, module in collections_plus_core.items():
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


def write_collection_metadata(
    collection_metadata: Dict[str, Any], collection_name: str
):
    if "_" in collection_name:
        raise ValueError(
            f"Names can only contain dashes, not underscores, got: {collection_name!r}"
        )

    collection_slug = collection_name.replace("-", "_")
    collection_version = importlib.import_module(collection_slug).__version__
    collection_metadata_path = (
        Path("blocks") / collection_name / f"v{collection_version}.json"
    )
    collection_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(collection_metadata_path, "w") as f:
        json.dump(collection_metadata, f, indent=2)


@flow
def update_block_metadata_for_collection(collection_name: str):
    collection_block_metadata = generate_all_block_metadata(collection_name)
    submit_updates(collection_block_metadata, "block")

if __name__ == "__main__":
    collection_name = argv[1]
    update_block_metadata_for_collection(collection_name)