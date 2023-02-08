import httpx, json

from prefect import flow, task
from prefect.tasks import task_input_hash
from typing import Any, Dict
from utils import get_collection_names, submit_updates

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

@task(
    name="Retrieve Collection Metadata",
    cache_key_fn=task_input_hash,
)
def generate_metadata_for_collection(collection_name: str) -> Dict[str, Any]:
    """
    Generates metadata for a collection.
    """
    return {
        collection_name: summarize_collection(collection_name)
    }

@flow(name="Update Collection Metadata")
def update_collection_package_metadata(collection_name: str):
    """
    Updates the collection metadata.
    """
    collection_metadata = generate_metadata_for_collection(collection_name)
    submit_updates(collection_metadata, "collection")

if __name__ == "__main__":
    update_collection_package_metadata("prefect-airbyte")