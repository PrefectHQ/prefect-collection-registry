import inspect
import json
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Callable, Dict, Generator, Union

import fastjsonschema
import github3
import httpx
from prefect import Flow, task
from prefect.blocks.system import Secret
from prefect.utilities.asyncutils import run_sync_in_worker_thread, sync_compatible
from prefect.utilities.importtools import load_module, to_qualified_name
from typing_extensions import Literal

import metadata_schemas

exclude_collections = {
    f"https://prefecthq.github.io/{collection}/"
    for collection in [
        "prefect-ray",
    ]
}

CollectionViewName = Literal["block", "flow", "worker"]


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


@task
def submit_updates(
    collection_metadata: Dict[str, Any],
    collection_name: str,
    branch_name: str,
    variety: CollectionViewName,
    repo_name: str = "prefect-collection-registry",
):
    """
    Submits updates to the collection registry.

    This task will attempt to create a new file in the collection registry repo
    at `collections/{collection_name}/{variety}s/{release_tag}.json` containing
    the contents of `collection_metadata`. It will also update the
    `views/aggregate-{variety}-metadata.json` file to include the new metadata for
    `collection_name`.

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

    # read the existing flow metadata from existing JSON file
    registry_repo = get_repo(repo_name)
    collection_repo = get_repo(collection_name)

    latest_release = collection_repo.latest_release().tag_name

    existing_metadata_content = registry_repo.file_contents(
        metadata_file, ref=branch_name
    ).decoded.decode()

    existing_metadata_dict = json.loads(existing_metadata_content)

    collection_metadata_with_outer_key = {collection_name: collection_metadata}

    existing_metadata_dict.update(collection_metadata_with_outer_key)

    updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

    # validate the new metadata
    validate_view_content(updated_metadata_dict, variety)

    # create a new commit adding the collection version metadata
    try:
        registry_repo.create_file(
            path=f"collections/{collection_name}/{variety}s/{latest_release}.json",
            message=f"Add `{collection_name}` `{latest_release}` to {variety} records",
            content=json.dumps(collection_metadata_with_outer_key, indent=2).encode(
                "utf-8"
            ),
            branch=branch_name,
        )
        print(f"Added {collection_name} {latest_release} to {variety} records!")
    except github3.exceptions.UnprocessableEntity as e:
        if '"sha" wasn\'t supplied' in str(e):
            # file already exists so nothing to update
            print(
                f"{variety} metadata for {collection_name} {latest_release} already exists!"
            )
            return
        else:
            raise

    # create a new commit updating the aggregate flow metadata file
    updated_metadata_content = json.dumps(updated_metadata_dict, indent=2)
    if existing_metadata_content == updated_metadata_content:
        print(
            f"Aggregate {variety} metadata for {collection_name} {latest_release} already up to date!"
        )
        return

    registry_repo.file_contents(metadata_file, ref=branch_name).update(
        message=f"Update aggregate {variety} metadata with `{collection_name}` `{latest_release}`",
        content=updated_metadata_content.encode("utf-8"),
        branch=branch_name,
    )

    print(
        f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
    )


def get_collection_names():
    repo_owner = "PrefectHQ"
    repo_name = "prefect-collection-registry"
    path = "collections"

    url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"

    headers = {"Accept": "application/vnd.github+json"}

    response = httpx.get(url, headers=headers)

    return [item["name"] for item in response.json() if item["type"] == "dir"]


def get_logo_url_for_collection(collection_name: str) -> str:
    """Returns the URL of the logo for a collection."""

    blocks_metadata = read_view_content("block")

    block_types_from_collection = blocks_metadata[collection_name]["block_types"]

    return block_types_from_collection.popitem()[1]["logo_url"]


def read_view_content(view: CollectionViewName) -> Dict[str, Any]:
    """Reads the content of a view from the views directory."""

    repo_organization = "PrefectHQ"
    repo_name = "prefect-collection-registry"

    repo_url = f"https://raw.githubusercontent.com/{repo_organization}/{repo_name}/main"

    view_filename = f"aggregate-{view}-metadata.json"

    resp = httpx.get(repo_url + f"/views/{view_filename}")
    resp.raise_for_status()
    return resp.json()


@sync_compatible
async def get_repo(name: str) -> github3.repos.repo.Repository:
    """Returns a GitHub repository object for a given collection name."""

    github_token = await Secret.load("collection-registry-github-token")
    gh = await run_sync_in_worker_thread(github3.login, token=github_token.get())
    return gh.repository("PrefectHQ", name)


def validate_view_content(view_dict: dict, variety: CollectionViewName) -> None:
    """Raises an error if the view content is not valid."""
    schema = getattr(metadata_schemas, f"{variety}_schema")
    validate = fastjsonschema.compile(schema)

    for collection_name, collection_metadata in view_dict.items():
        try:
            validate(list(collection_metadata.values())[0])
        except IndexError:
            raise ValueError("There's a key with no value in this view!")
        print(f"Validated {collection_name} {variety} view!")
