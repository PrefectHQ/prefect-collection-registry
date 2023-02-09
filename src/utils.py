import json
from types import ModuleType
from typing import Any, Callable, Dict, Union

import github3
import httpx
from bs4 import BeautifulSoup
from prefect import task
from prefect.blocks.core import Block
from prefect.blocks.system import Secret
from prefect.utilities.importtools import to_qualified_name
from pydantic import Field
from typing_extensions import Literal

exclude_collections = {"prefect-ray"}


class LatestReleases(Block):
    releases: Dict[str, str] = Field(
        default_factory=dict,
        description="A dictionary of the latest releases for each Prefect library.",
    )

    def get(self, collection_name: str) -> str | None:
        if collection_name not in self.releases:
            return None
        return self.releases[collection_name]

    def set(self, collection_name: str, release: str) -> None:
        self.releases[collection_name] = release


class FlowLinks(Block):
    _block_type_slug = "flow-links"

    links: Dict[str, Any] = Field(
        default_factory=dict,
        description="A dictionary of the locations of each flow in a collection.",
    )

    def get(self, flow_slug: str, key: str) -> str | None:
        if flow_slug not in self.links or key not in self.links[flow_slug]:
            return None
        return self.links[flow_slug][key]

    def set(self, flow_slug: str, key: str, value: str) -> None:

        if flow_slug not in self.links:
            self.links[flow_slug] = {}

        self.links[flow_slug][key] = value

    def get_doc_url(self, flow_slug: str) -> str | None:
        submodule = self.get(flow_slug, "submodule")
        if submodule is None:
            return None
        return (
            "https://prefecthq.github.io/"
            f"{submodule.replace('.', '/').replace('_', '-')}/"
            f"#{submodule}."
            f"{flow_slug}"
        )


def get_collection_names():
    catalog_resp = httpx.get("https://docs.prefect.io/collections/catalog/")
    catalog_soup = BeautifulSoup(catalog_resp.text, "html.parser")
    repo_api_urls = sorted(
        {
            url["href"]
            .replace("https://", "https://api.github.com/repos/")
            .replace(".github.io", "")
            .rstrip("/")
            for url in catalog_soup.find_all("a", href=True)
            if ".io/prefect-" in url["href"]
        }
    )
    return [
        i.split("/")[-1]
        for i in repo_api_urls
        if i.split("/")[-2] == "prefecthq"
        and i.split("/")[-1] not in exclude_collections
    ]


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


@task
def submit_updates(
    collection_metadata: Dict[str, Any],
    variety: Literal["block", "flow", "collection"],
):

    collection_name = list(collection_metadata.keys())[0]
    metadata_file = f"views/aggregate-{variety}-metadata.json"
    REPO_NAME = "prefect-collection-registry"
    BRANCH_NAME = "flow-metadata"

    # read the existing flow metadata from existing JSON file
    github_token = Secret.load("github-token")
    gh = github3.login(token=github_token.get())
    repo = gh.repository("PrefectHQ", REPO_NAME)

    existing_metadata_content = repo.file_contents(
        metadata_file, ref=BRANCH_NAME
    ).decoded.decode()

    existing_metadata_dict = dict(sorted(json.loads(existing_metadata_content).items()))

    collection_repo = gh.repository("PrefectHQ", collection_name)

    latest_release = collection_repo.latest_release().tag_name

    existing_metadata_dict.update(collection_metadata)

    # create a new commit adding the collection version metadata
    try:
        repo.create_file(
            path=f"{variety}s/{collection_name}/{latest_release}.json",
            message=f"Add {collection_name} {latest_release} to {variety} records",
            content=json.dumps(collection_metadata, indent=4).encode("utf-8"),
            branch=BRANCH_NAME,
        )
    except github3.exceptions.UnprocessableEntity as e:
        if '"sha" wasn\'t supplied' in str(e):
            # file already exists so nothing to do
            print(
                f"{variety} metadata for {collection_name} {latest_release} already exists!"
            )
        else:
            raise

    # create a new commit updating the aggregate flow metadata file
    updated_metadata_content = json.dumps(existing_metadata_dict, indent=4)
    if existing_metadata_content == updated_metadata_content:
        print(
            f"Aggregate {variety} metadata for {collection_name} {latest_release} already up to date!"
        )
        return

    repo.file_contents(metadata_file, ref=BRANCH_NAME).update(
        message=f"Update aggregate {variety} metadata with {collection_name} {latest_release}",
        content=updated_metadata_content.encode("utf-8"),
        branch=BRANCH_NAME,
    )

    print(
        f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
    )


def read_view_content(view: Literal["block", "flow", "collection"]) -> Dict[str, Any]:
    """Reads the content of a view from the views directory."""

    repo_organization = "PrefectHQ"
    repo_name = "prefect-collection-registry"

    repo_url = f"https://raw.githubusercontent.com/{repo_organization}/{repo_name}/main"

    view_filename = f"aggregate-{view}-metadata.json"

    resp = httpx.get(repo_url + f"/views/{view_filename}")
    resp.raise_for_status()
    return resp.json()


def get_logo_url_for_collection(collection_name: str) -> str:
    """Returns the URL of the logo for a collection."""

    blocks_metadata = read_view_content("block")

    block_types_from_collection = blocks_metadata[collection_name]["block_types"]

    return block_types_from_collection.popitem()[1]["logo_url"]
