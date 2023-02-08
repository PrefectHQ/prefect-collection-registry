from typing import Any, Dict

import httpx
from prefect import flow, task

from utils import submit_updates


def summarize_collection(collection_name: str) -> Dict[str, Any]:
    """
    Summarizes a collection. Can be refined to include more information.
    """

    response = httpx.get(f"https://pypi.org/pypi/{collection_name}/json")
    info = response.json()["info"]

    return {
        "name": info["name"],
        "author": info["author"],
        "latest_version": info["version"],
        "downloads": info["downloads"],
        "keywords": info["keywords"],
        "home_page": info["home_page"],
        "package_url": info["package_url"],
        "requires_dist": info["requires_dist"],
        "requires_python": info["requires_python"],
    }


@task(name="Retrieve Collection Metadata")
def generate_metadata_for_collection(collection_name: str) -> Dict[str, Any]:
    """
    Generates metadata for a collection.
    """
    return {collection_name: summarize_collection(collection_name)}


@flow(name="Update Collection Metadata", log_prints=True)
def update_collection_package_metadata(collection_name: str):
    """
    Updates the collection metadata.
    """
    collection_metadata = generate_metadata_for_collection(collection_name)
    submit_updates(collection_metadata, "collection")
