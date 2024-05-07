import inspect
import json
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Callable, Dict, Generator, List, Union

import fastjsonschema
import github3
import httpx
from prefect import Flow, task
from prefect.blocks.core import Block
from prefect.blocks.system import Secret
from prefect.client.cloud import get_cloud_client
from prefect.settings import PREFECT_API_URL
from prefect.utilities.asyncutils import run_sync_in_worker_thread  # noqa
from prefect.utilities.asyncutils import sync_compatible
from prefect.utilities.importtools import load_module, to_qualified_name
from typing_extensions import Literal

CollectionViewVariety = Literal["block", "flow", "worker"]


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


@task
def submit_updates(
    collection_metadata: Dict[str, Any],
    collection_name: str,
    branch_name: str,
    variety: CollectionViewVariety,
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

    if not latest_release.startswith("v"):
        latest_release = "v" + latest_release

    existing_metadata_content = registry_repo.file_contents(
        metadata_file, ref=branch_name
    ).decoded.decode()

    existing_metadata_dict = json.loads(existing_metadata_content)

    collection_metadata_with_outer_key = {collection_name: collection_metadata}

    existing_metadata_dict.update(collection_metadata_with_outer_key)

    updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

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
                f"{variety} metadata for {collection_name} {latest_release} already"
                " exists!"
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
                f"Aggregate {variety} metadata for"
                f" {collection_name} {latest_release} already up to date!"
            )
            return

        registry_repo.file_contents(metadata_file, ref=branch_name).update(
            message=(
                f"Update aggregate {variety} metadata with `{collection_name}`"
                f" `{latest_release}`"
            ),
            content=updated_metadata_content.encode("utf-8"),
            branch=branch_name,
        )

        print(
            f"Updated aggregate {variety} metadata for"
            f" {collection_name} {latest_release}!"
        )


def get_collection_names():
    repo_owner = "PrefectHQ"
    repo_name = "Prefect"
    path = "docs/integrations/catalog"

    response = httpx.get(
        url=f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}",
        headers={"Accept": "application/vnd.github+json"},
    )
    return [file['name'] for file in response if file['type'] == 'file' and file['name'] != "TEMPLATE.yaml"]


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


@sync_compatible
async def get_repo(name: str) -> github3.repos.repo.Repository:
    """Returns a GitHub repository object for a given collection name."""

    github_token = await Secret.load("collection-registry-contents-prs-rw-pat")
    gh = await run_sync_in_worker_thread(github3.login, token=github_token.get())
    return gh.repository("PrefectHQ", name)


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


@sync_compatible
async def result_storage_from_env() -> Block | None:
    env_to_storage_block_name = {
        "inconspicuous-pond": "s3/flow-script-storage",
        "integrations": "gcs/collection-registry-result-storage",
    }

    async with get_cloud_client() as client:
        current_workspace_id = PREFECT_API_URL.value().split("/")[-1]

        for workspace in await client.read_workspaces():
            if str(workspace.workspace_id) == current_workspace_id:
                result_storage_name = env_to_storage_block_name[
                    workspace.workspace_name
                ]
                return await Block.load(name=result_storage_name)
