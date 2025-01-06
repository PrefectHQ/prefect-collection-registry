import importlib
import inspect
import json
import logging
from abc import ABC
from importlib.metadata import entry_points
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import fastjsonschema
from prefect import flow
from prefect.blocks.core import Block
from prefect.plugins import safe_load_entrypoints

from prefect_collection_registry import utils
from prefect_collection_registry.metadata_schemas import block_schema

# Some collection blocks share names with core blocks. We exclude them
# from the registry for now to avoid confusion.
BLOCKS_BLOCKLIST: set[str] = {
    "k8s-job",
    "custom-webhook",
    "slack-incoming-webhook",
    "secret-str",
    "secret-int",
    "secret-dict",
    "secret-list",
    "secret-float",
}


def generate_block_metadata(block_subcls: type[Block]) -> dict[str, Any]:
    """
    Takes a block subclass and returns a JSON dict representation of
    its corresponding block type and block schema.
    """
    block_type_dict = block_subcls._to_block_type().model_dump(  # type: ignore
        exclude={"id", "created", "updated", "is_protected"},
        mode="json",
    )
    block_type_dict["block_schema"] = block_subcls._to_block_schema(  # type: ignore
        block_type_id=uuid4()
    ).model_dump(
        exclude={"id", "created", "updated", "block_type_id", "block_type"},
        mode="json",
    )

    # make it deterministic to prevent false positives of changes
    block_type_dict["block_schema"]["capabilities"] = sorted(
        block_type_dict["block_schema"]["capabilities"]
    )
    validate = fastjsonschema.compile(block_schema)  # type: ignore
    validate(block_type_dict)  # type: ignore

    return block_type_dict


def generate_prefect_block_metadata() -> dict[str, Any]:
    """Generates block metadata from the prefect package."""
    from prefect.utilities.dispatch import get_registry_for_type

    block_registry = get_registry_for_type(Block) or {}

    return {
        "block_types": dict(
            sorted(
                {
                    slug: generate_block_metadata(subcls)
                    for slug, subcls in block_registry.items()
                    if slug not in BLOCKS_BLOCKLIST
                }.items()
            )
        )
    }


def generate_block_metadata_for_module(module: ModuleType) -> dict[str, Any]:
    block_subclasses = discover_block_subclasses(module)
    return dict(
        sorted(
            {
                block_subcls.get_block_type_slug(): generate_block_metadata(
                    block_subcls
                )
                for block_subcls in block_subclasses
                if block_subcls.get_block_type_slug() not in BLOCKS_BLOCKLIST
            }.items()
        )
    )


def discover_block_subclasses(module: ModuleType) -> list[type[Block]]:
    return [
        cls
        for _, cls in inspect.getmembers(module)
        if Block.is_block_class(cls)
        and cls.__name__ != "Block"
        and ABC not in getattr(cls, "__bases__", [])
    ]


def generate_block_metadata_for_collection(collection_name: str) -> dict[str, Any]:
    if collection_name == "prefect":
        return generate_prefect_block_metadata()

    # group is only available for Python 3.10+
    collections = safe_load_entrypoints(entry_points(group="prefect.collections"))
    output_dict: dict[str, Any] = {}
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

        # Add description to each block type of what collection it's from and how to install it.
        added_description = (
            f" This block is part of the {collection_name} collection. "
            f"Install {collection_name} with `pip install {collection_name}` "
            "to use this block."
        )
        for block_type in output_dict["block_types"].keys():
            output_dict["block_types"][block_type]["description"] += added_description

    return output_dict


def write_block_metadata(collection_metadata: dict[str, Any], collection_name: str):
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


@flow(name="update-block-metadata-for-collection")
async def update_block_metadata_for_collection(collection_name: str, branch_name: str):
    block_metadata = generate_block_metadata_for_collection(collection_name)
    await utils.submit_updates(
        collection_metadata=block_metadata,
        collection_name=collection_name,
        branch_name=branch_name,
        variety="block",
    )
