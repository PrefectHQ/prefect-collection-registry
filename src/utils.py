import asyncio
import inspect
import json
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Callable, Dict, Generator, List, Union

import fastjsonschema
import httpx
from gh_util.client import GHClient
from gh_util.functions import (
    create_commit,
    fetch_latest_release,
    get_filenames_from_directory,
)
from gh_util.logging import get_logger
from packaging import version
from prefect import Flow, task
from prefect.utilities.importtools import load_module, to_qualified_name
from pydantic_core import from_json
from typing_extensions import Literal

logger = get_logger(__name__)

CollectionViewVariety = Literal["block", "flow", "worker"]

INCLUDE_COLLECTIONS = [
    "prefect",
    "prefect-aws",
    "prefect-bitbucket",
    "prefect-kubernetes",
    "prefect-dask",
    "prefect-databricks",
    "prefect-gitlab",
    "prefect-shell",
    "prefect-dbt",
    "prefect-gcp",
    "prefect-snowflake",
    "prefect-sqlalchemy",
    "prefect-azure",
]


def pad_text(
    text: str | List[str],
    header: str = None,
    padding_character: str = "\n",
    n_padding: int = 3,
) -> str:
    """
    Adds padding characters to either side of `text` and an optional header
    padded with the same spacing.

    Defaults to 3 newlines and no header.
    """
    padding = padding_character * n_padding
    padded_header = header + padding if header else ""

    text = "".join(text) if isinstance(text, list) else text

    return f"{padding}{padded_header}{text}{padding}"


def skip_parsing(name: str, obj: Union[ModuleType, Callable], module_nesting: str):
    """
    Skips parsing the object if it's a private object or if it's not in the
    module nesting, preventing imports from other libraries from being added to the
    examples catalog.
    """

    try:
        wrong_module = not to_qualified_name(obj).startswith(module_nesting)
    except AttributeError:
        wrong_module = False
    return obj.__doc__ is None or name.startswith("_") or wrong_module


def find_flows_in_module(
    module_name: str,
) -> Generator[Flow, None, None]:
    """
    Finds all flows in a module.
    """
    module = load_module(module_name)

    for _, name, ispkg in iter_modules(module.__path__):
        if ispkg:
            # catch submodules that are not top-level
            # e.g. prefect-hightouch.syncs.flows
            yield from find_flows_in_module(f"{module_name}.{name}")
        else:
            try:
                submodule = load_module(f"{module_name}.{name}")
                print(f"\tLoaded submodule {module_name}.{name}...")
            except ModuleNotFoundError:
                continue

            for _, obj in inspect.getmembers(submodule):
                if skip_parsing(name, obj, module_name):
                    continue
                if isinstance(obj, Flow):
                    yield obj


async def read_file_from_repo(
    owner: str, repo: str, file_path: str, ref: str = "main"
) -> str:
    """Read the content of a file from a remote repository."""
    async with GHClient() as client:
        response = await client.get(
            f"/repos/{owner}/{repo}/contents/{file_path}",
            params={"ref": ref},
        )

        data = response.json()
        if data["type"] == "file":
            content = await client.get(data["download_url"])
            logger.debug_kv(
                "Read file content",
                f"Successfully read content of file '{file_path}' from repository '{owner}/{repo}'",
                "green",
            )
            return content.text
        else:
            logger.warning_kv(
                "Not a file",
                f"The path '{file_path}' does not refer to a file in the repository '{owner}/{repo}'",
                "yellow",
            )
            return ""


@task
async def submit_updates(
    collection_metadata: Dict[str, Any],
    collection_name: str,
    branch_name: str,
    variety: CollectionViewVariety,
    repo_name: str = "prefect-collection-registry",
):
    """
    Submits updates to the collection registry.
    This task will attempt to create a new file in the collection registry repo at
    `collections/{collection_name}/{variety}s/{release_tag}.json` containing the contents of `collection_metadata`.
    It will also update the `views/aggregate-{variety}-metadata.json` file to include the new metadata for `collection_name`.
    Args:
        collection_metadata: dict of metadata of a given `variety` for `collection_name`
        collection_name: name of the collection
        branch_name: name of the branch to submit updates to
        variety: the variety of metadata to submit
        repo_name: name of the collection registry repo
    """
    if branch_name == "main":
        raise ValueError("Cannot submit updates directly to main!")

    metadata_file = f"views/aggregate-{variety}-metadata.json"

    latest_release = await fetch_latest_release("prefecthq", collection_name)
    if not latest_release.startswith("v"):
        latest_release = "v" + latest_release

    existing_metadata_content = await read_file_from_repo(
        "PrefectHQ", repo_name, metadata_file, ref=branch_name
    )
    existing_metadata_dict = from_json(existing_metadata_content)
    collection_metadata_with_outer_key = {collection_name: collection_metadata}
    existing_metadata_dict.update(collection_metadata_with_outer_key)
    updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

    # create a new commit adding the collection version metadata
    try:
        await create_commit(
            owner="PrefectHQ",
            repo=repo_name,
            path=f"collections/{collection_name}/{variety}s/{latest_release}.json",
            content=json.dumps(collection_metadata_with_outer_key, indent=2),
            message=f"Add `{collection_name}` `{latest_release}` to {variety} records",
            branch=branch_name,
            create_branch=True,
        )
        print(f"Added {collection_name} {latest_release} to {variety} records!")
    except Exception as e:
        if "Reference already exists" in str(e):
            # file already exists so nothing to update
            print(
                f"{variety} metadata for {collection_name} {latest_release} already exists!"
            )
            return
        else:
            raise

    # don't update the aggregate metadata with keys that have empty values
    if collection_metadata:
        # validate the new metadata
        validate_view_content(updated_metadata_dict, variety)

        # create a new commit updating the aggregate flow metadata file
        updated_metadata_content = json.dumps(updated_metadata_dict, indent=2)

        if existing_metadata_content == updated_metadata_content:
            print(
                f"Aggregate {variety} metadata for {collection_name} {latest_release} already up to date!"
            )
            return

        await create_commit(
            owner="PrefectHQ",
            repo=repo_name,
            path=metadata_file,
            content=updated_metadata_content,
            message=f"Update aggregate {variety} metadata with `{collection_name}` `{latest_release}`",
            branch=branch_name,
            create_branch=True,
        )
        print(
            f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
        )


def get_collection_names(
    repo_owner="PrefectHQ",
    repo_name="prefect-collection-registry",
    path="collections",
    include_all: bool = False,
) -> List[str]:
    if not include_all:
        return INCLUDE_COLLECTIONS

    response = httpx.get(
        url=f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}",
        headers={"Accept": "application/vnd.github+json"},
    )

    return [item["name"] for item in response.json() if item["type"] == "dir"]


async def get_collections_to_update() -> list[str]:
    collections = get_collection_names()

    async def _collection_needs_update(collection: str) -> bool:
        latest_release_tag = (
            await fetch_latest_release("prefecthq", collection)
        ).tag_name

        recorded_releases_for_collection = await get_filenames_from_directory(
            "prefecthq",
            "prefect-collection-registry",
            f"collections/{collection}/blocks",
            "*.json",
        )

        if not recorded_releases_for_collection:
            return True

        latest_recorded_release_tag = max(
            recorded_releases_for_collection,
            key=lambda x: version.parse(x.replace(".json", "")),
        ).replace(".json", "")

        if collection == "prefect":
            latest_release_tag = "v" + latest_release_tag

        return latest_release_tag != latest_recorded_release_tag

    needs_updates = await asyncio.gather(
        *(_collection_needs_update(collection) for collection in collections)
    )

    return [
        collection
        for collection, needs_update in zip(collections, needs_updates)
        if needs_update
    ]


def get_logo_url_for_collection(collection_name: str) -> str:
    """Returns the URL of the logo for a collection."""

    blocks_metadata = read_view_content("block")

    block_types_from_collection = blocks_metadata[collection_name]["block_types"]

    return block_types_from_collection.popitem()[1]["logo_url"]


def read_view_content(view: CollectionViewVariety) -> Dict[str, Any]:
    """Reads the content of a view from the views directory."""

    repo_organization = "PrefectHQ"
    repo_name = "prefect-collection-registry"

    repo_url = f"https://raw.githubusercontent.com/{repo_organization}/{repo_name}/main"

    view_filename = f"aggregate-{view}-metadata.json"

    resp = httpx.get(repo_url + f"/views/{view_filename}")
    resp.raise_for_status()
    return resp.json()


def validate_view_content(view_dict: dict, variety: CollectionViewVariety) -> None:
    """Raises an error if the view content is not valid."""
    import metadata_schemas

    schema = getattr(metadata_schemas, f"{variety}_schema")
    validate = fastjsonschema.compile(schema)

    for collection_name, collection_metadata in view_dict.items():
        if variety == "block":
            collection_metadata = collection_metadata["block_types"]
        try:
            # raise validation errors if any metadata doesn't match the schema
            list(map(validate, collection_metadata.values()))
        except IndexError:  # to catch something like {"prefect-X": {}}
            raise ValueError("There's a key with empty value in this view!")
        print(f"  Validated {collection_name} summary in {variety} view!")
