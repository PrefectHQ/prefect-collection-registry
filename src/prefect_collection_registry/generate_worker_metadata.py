import importlib
import inspect
import json
import logging
from importlib.metadata import entry_points
from pathlib import Path
from sys import argv
from types import ModuleType
from typing import Any

import fastjsonschema
from prefect import task
from prefect.plugins import safe_load_entrypoints
from prefect.utilities.dispatch import get_registry_for_type
from prefect.utilities.importtools import to_qualified_name
from prefect.workers.base import BaseWorker

from prefect_collection_registry.metadata_schemas import worker_schema
from prefect_collection_registry.utils import submit_updates

# `block` work pool types should only be created via
# `Infrastructure.publish_as_work_pool`
# See https://github.com/PrefectHQ/prefect/pull/11180 for more details
WORKERS_BLOCKLIST: set[str] = {"BaseWorker", "BlockWorker"}


@task
def generate_worker_metadata(
    worker_subcls: type[BaseWorker], package_name: str
) -> dict[str, Any]:
    """Generates worker metadata."""
    worker_metadata: dict[str, Any] = dict(
        sorted(
            {  # type: ignore
                "type": worker_subcls.type,
                "install_command": f"pip install {package_name}",
                "description": worker_subcls.get_description(),
                "display_name": getattr(
                    worker_subcls, "_display_name", worker_subcls.type
                ),
                "logo_url": worker_subcls.get_logo_url(),
                "documentation_url": worker_subcls.get_documentation_url(),
                "default_base_job_configuration": (
                    worker_subcls.get_default_base_job_template()  # type: ignore
                ),
                "is_beta": getattr(worker_subcls, "_is_beta", False),
            }.items()
        )
    )
    validate = fastjsonschema.compile(worker_schema)  # type: ignore
    validate(worker_metadata)  # type: ignore

    return worker_metadata


@task
def get_worker_metadata_from_prefect():
    """Gets worker metadata from prefect."""
    worker_registry = get_registry_for_type(BaseWorker) or {}

    output: dict[str, Any] = {
        "prefect-agent": {
            "type": "prefect-agent",
            "documentation_url": (
                "https://docs.prefect.io/latest/concepts/work-pools/#agent-overview"
            ),
            "display_name": "Prefect Agent",
            "logo_url": "https://cdn.sanity.io/images/3ugk85nk/production/c771bb53894c877e169c8db158c5598558b8f175-24x24.svg",
            "install_command": "pip install prefect",
            "default_base_job_configuration": {},
            "description": (
                "Execute flow runs on heterogeneous infrastructure using infrastructure"
                " blocks."
            ),
        }
    }

    metadata: dict[str, Any] = {
        worker_subcls.type: generate_worker_metadata(
            worker_subcls=worker_subcls, package_name="prefect"
        )
        for worker_subcls in worker_registry.values()
        if (
            to_qualified_name(worker_subcls).startswith("prefect.")
            and worker_subcls.__name__ not in WORKERS_BLOCKLIST
        )
    }

    output.update(metadata)
    output = dict(sorted(output.items()))
    return output


@task
def get_worker_metadata_from_collection(collection_name: str) -> dict[str, Any]:
    """Gets worker metadata from a given collection."""
    collections = safe_load_entrypoints(entry_points(group="prefect.collections"))

    output: dict[str, Any] = {}
    for ep_name, module in collections.items():
        if isinstance(module, Exception):
            logging.warning(f"Error loading collection entrypoint {ep_name} - skipping")
            continue
        discovered_collection_name = module.__name__.split(".")[0].replace("_", "-")
        if collection_name != discovered_collection_name:
            continue

        worker_subclasses = discover_base_worker_subclasses(module)
        for worker_subcls in worker_subclasses:
            output[worker_subcls.type] = generate_worker_metadata(
                worker_subcls=worker_subcls, package_name=collection_name
            )

    output = dict(sorted(output.items()))
    return output


@task
def discover_base_worker_subclasses(module: ModuleType) -> list[type[BaseWorker]]:
    """Discovers all subclasses of BaseWorker in a given module."""
    return [
        cls
        for _, cls in inspect.getmembers(module)
        if inspect.isclass(cls)
        and issubclass(cls, BaseWorker)
        and cls.__name__ not in WORKERS_BLOCKLIST
    ]


def write_worker_metadata(worker_metadata: dict[str, Any], package_name: str):
    """Writes worker metadata to a file."""
    if "_" in package_name:
        raise ValueError(
            f"Names can only contain dashes, not underscores, got: {package_name!r}"
        )

    package_slug = package_name.replace("-", "_")
    package_version = importlib.import_module(package_slug).__version__
    collection_metadata_path = (
        Path("collections") / package_name / "workers" / f"v{package_version}.json"
    )
    collection_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(collection_metadata_path, "w") as f:
        json.dump(worker_metadata, f, indent=2)


@task
def generate_worker_metadata_for_package(package_name: str) -> dict[str, Any]:
    """Generates worker metadata for workers in a given package."""
    if package_name == "prefect":
        return get_worker_metadata_from_prefect()
    else:
        return get_worker_metadata_from_collection(package_name)


@task
async def update_worker_metadata_for_package(package_name: str, branch_name: str):
    """Generates and submits worker metadata for a given package."""
    worker_metadata = generate_worker_metadata_for_package(package_name=package_name)
    await submit_updates(
        collection_metadata=worker_metadata,
        collection_name=package_name,
        branch_name=branch_name,
        variety="worker",
    )


if __name__ == "__main__":
    package_name = argv[1]
    worker_metadata = generate_worker_metadata_for_package(package_name=argv[1])
    write_worker_metadata(worker_metadata=worker_metadata, package_name=argv[1])
