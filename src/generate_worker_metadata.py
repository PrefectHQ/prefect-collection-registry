import importlib
import inspect
import json
import logging
from importlib.metadata import entry_points
from pathlib import Path
from sys import argv
from types import ModuleType
from typing import Any, Dict, List, Type

import fastjsonschema
from prefect import flow, task
from prefect.experimental.workers.base import BaseWorker
from prefect.plugins import safe_load_entrypoints
from prefect.utilities.dispatch import get_registry_for_type

from metadata_schemas import worker_schema


@task
def generate_worker_metadata(worker_subcls: Type[BaseWorker], package_name: str):
    """Generates worker metadata."""

    worker_metadata = dict(
        sorted(
            {
                "type": worker_subcls.type,
                "install_command": f"pip install {package_name}",
                "description": worker_subcls.get_description(),
                "logo_url": worker_subcls.get_logo_url(),
                "documentation_url": worker_subcls.get_documentation_url(),
                "default_base_job_configuration": worker_subcls.get_default_base_job_template(),
            }.items()
        )
    )
    validate = fastjsonschema.compile(worker_schema)
    validate(worker_metadata)

    return worker_metadata


@flow
def get_worker_metadata_from_prefect():
    """Gets worker metadata from prefect."""

    worker_registry = get_registry_for_type(BaseWorker) or {}

    output = {
        "workers": {
            "prefect-agent": {
                "type": "prefect-agent",
                "install_command": "pip install prefect",
                "default_base_job_configuration": {},
                "description": "A Prefect agent that executes flow runs via infrastructure blocks.",
            }
        }
    }

    metadata = {
        worker_subcls.type: generate_worker_metadata(
            worker_subcls=worker_subcls, package_name="prefect"
        )
        for worker_subcls in worker_registry.values()
    }

    output["workers"].update(metadata)
    output["workers"] = dict(sorted(output["workers"].items()))
    return output


@flow
def get_worker_metadata_from_collection(collection_name: str):
    """Gets worker metadata from a given collection."""
    collections = safe_load_entrypoints(entry_points(group="prefect.collections"))

    output = {"workers": {}}
    for ep_name, module in collections.items():
        if isinstance(module, Exception):
            logging.warning(f"Error loading collection entrypoint {ep_name} - skipping")
            continue
        discovered_collection_name = module.__name__.split(".")[0].replace("_", "-")
        if collection_name != discovered_collection_name:
            continue

        worker_subclasses = discover_base_worker_subclasses(module)
        for worker_subcls in worker_subclasses:
            output["workers"].update(
                generate_worker_metadata(
                    worker_subcls=worker_subcls, package_name=collection_name
                )
            )

    output["workers"] = dict(sorted(output["workers"].items()))
    return output


@task
def discover_base_worker_subclasses(module: ModuleType) -> List[Type[BaseWorker]]:
    return [
        cls
        for _, cls in inspect.getmembers(module)
        if inspect.isclass(cls)
        and issubclass(cls, BaseWorker)
        and cls.__name__ != "BaseWorker"
    ]


@task
def write_worker_metadata(worker_metadata: Dict[str, Any], package_name: str):
    if "_" in package_name:
        raise ValueError(
            f"Names can only contain dashes, not underscores, got: {package_name!r}"
        )

    package_slug = package_name.replace("-", "_")
    package_version = importlib.import_module(package_slug).__version__
    collection_metadata_path = (
        Path("collections") / package_name / "workers" / f"{package_version}.json"
    )
    collection_metadata_path.parent.mkdir(parents=True, exist_ok=True)
    with open(collection_metadata_path, "w") as f:
        json.dump(worker_metadata, f, indent=2)


@flow
def generate_worker_metadata_for_package(package_name: str):
    """Updates the worker metadata for workers in a given package."""
    if package_name == "prefect":
        return get_worker_metadata_from_prefect()
    else:
        return get_worker_metadata_from_collection(package_name)


@flow
def update_worker_metadata_for_package(package_name: str):
    worker_metadata = generate_worker_metadata_for_package(package_name=package_name)
    write_worker_metadata(worker_metadata=worker_metadata, package_name=package_name)


if __name__ == "__main__":
    package_name = argv[1]
    update_worker_metadata_for_package(package_name=package_name)
