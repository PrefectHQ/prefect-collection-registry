import inspect
import json
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Callable, Dict, Generator, Union

import github3
import httpx
from bs4 import BeautifulSoup
from prefect import Flow, task
from prefect.blocks.system import Secret
from prefect.utilities.importtools import load_module, to_qualified_name
from typing_extensions import Literal

exclude_collections = {
    f"https://prefecthq.github.io/{collection}/"
    for collection in [
        "prefect-ray",
    ]
}


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
    variety: Literal["block", "flow", "collection"],
    repo_name: str = "prefect-collection-registry",
    branch_name: str = "flow-metadata",
):

    collection_name = list(collection_metadata.keys())[0]
    metadata_file = f"views/aggregate-{variety}-metadata.json"

    # read the existing flow metadata from existing JSON file
    github_token = Secret.load("github-token")
    gh = github3.login(token=github_token.get())
    repo = gh.repository("PrefectHQ", repo_name)
    collection_repo = gh.repository("PrefectHQ", collection_name)
    latest_release = collection_repo.latest_release().tag_name

    existing_metadata_content = repo.file_contents(
        metadata_file, ref=branch_name
    ).decoded.decode()

    existing_metadata_dict = json.loads(existing_metadata_content)

    existing_metadata_dict.update(collection_metadata)

    updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

    # create a new commit adding the collection version metadata
    try:
        repo.create_file(
            path=f"collections/{collection_name}/{variety}s/{latest_release}.json",
            message=f"Add {collection_name} {latest_release} to {variety} records",
            content=json.dumps(collection_metadata, indent=4).encode("utf-8"),
            branch=branch_name,
        )
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
    updated_metadata_content = json.dumps(updated_metadata_dict, indent=4)
    if existing_metadata_content == updated_metadata_content:
        print(
            f"Aggregate {variety} metadata for {collection_name} {latest_release} already up to date!"
        )
        return

    repo.file_contents(metadata_file, ref=branch_name).update(
        message=f"Update aggregate {variety} metadata with {collection_name} {latest_release}",
        content=updated_metadata_content.encode("utf-8"),
        branch=branch_name,
    )

    print(
        f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
    )


def get_collection_names():
    catalog_resp = httpx.get("https://docs.prefect.io/collections/catalog/")
    catalog_soup = BeautifulSoup(catalog_resp.text, "html.parser")
    return sorted(
        {
            url.split("/")[-2]
            for div in catalog_soup.find_all("div", class_="collection-item")
            if "prefecthq.github.io" in (url := div.find("a")["href"])
            and url not in exclude_collections
        }
    )


def get_logo_url_for_collection(collection_name: str) -> str:
    """Returns the URL of the logo for a collection."""

    blocks_metadata = read_view_content("block")

    block_types_from_collection = blocks_metadata[collection_name]["block_types"]

    return block_types_from_collection.popitem()[1]["logo_url"]


def read_view_content(view: Literal["block", "flow", "collection"]) -> Dict[str, Any]:
    """Reads the content of a view from the views directory."""

    repo_organization = "PrefectHQ"
    repo_name = "prefect-collection-registry"

    repo_url = f"https://raw.githubusercontent.com/{repo_organization}/{repo_name}/main"

    view_filename = f"aggregate-{view}-metadata.json"

    resp = httpx.get(repo_url + f"/views/{view_filename}")
    resp.raise_for_status()
    return resp.json()
