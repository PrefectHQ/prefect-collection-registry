import github3, httpx, json
from bs4 import BeautifulSoup
from prefect import task
from prefect.blocks.system import Secret
from prefect.utilities.importtools import to_qualified_name
from types import ModuleType
from typing import Any, Callable, Dict, Union
from typing_extensions import Literal

exclude_collections = {
    "prefect-ray"
}

def get_collection_names():
    catalog_resp = httpx.get("https://docs.prefect.io/collections/catalog/")
    catalog_soup = BeautifulSoup(catalog_resp.text, "html.parser")
    repo_api_urls = sorted({
        url["href"]
        .replace("https://", "https://api.github.com/repos/")
        .replace(".github.io", "")
        .rstrip("/")
        for url in catalog_soup.find_all("a", href=True)
        if ".io/prefect-" in url["href"]
    })
    return [
        i.split("/")[-1] for i in repo_api_urls
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

    existing_metadata_raw = repo.file_contents(
        metadata_file, ref=BRANCH_NAME
    ).decoded.decode()

    metadata_dict = json.loads(existing_metadata_raw)

    print(collection_name)

    collection_repo = gh.repository("PrefectHQ", collection_name)
    
    
    latest_release = collection_repo.latest_release().tag_name
    
    metadata_dict.update(collection_metadata)
    
    # create a new commit adding the collection version metadata
    try:
        repo.create_file(
            path=f"{variety}s/{collection_name}/{latest_release}.json",
            message=f"Add {collection_name} {latest_release} to {variety} records",
            content=json.dumps(collection_metadata, indent=4).encode("utf-8"),
            branch=BRANCH_NAME,
        )
    except github3.exceptions.UnprocessableEntity as e:
        if "\"sha\" wasn't supplied" in str(e):
            # file already exists so nothing to do
            print(f"{variety} metadata for {collection_name} {latest_release} already exists!")
        else:
            raise
    
    # create a new commit updating the aggregate flow metadata file
    repo.file_contents(metadata_file, ref=BRANCH_NAME).update(
        message=f"Update aggregate {variety} metadata with {collection_name} {latest_release}",
        content=json.dumps(metadata_dict, indent=4).encode("utf-8"),
        branch=BRANCH_NAME,
    )

    print(f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!")