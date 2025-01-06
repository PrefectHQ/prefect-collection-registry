import asyncio
import base64
import inspect
import json
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Callable, Dict, Generator, Union

import fastjsonschema
import httpx
import yaml
from gh_util.client import GHClient
from gh_util.types import GitHubRepo
from prefect import Flow, task
from prefect.blocks.system import Secret
from prefect.utilities.importtools import load_module, to_qualified_name
from typing_extensions import Literal

CollectionViewVariety = Literal["block", "flow", "worker"]


def pad_text(
    text: str | list[str],
    header: str | None = None,
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


def skip_parsing(
    name: str, obj: Union[ModuleType, Callable[..., Any]], module_nesting: str
) -> bool:
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
) -> Generator[Flow[..., Any], None, None]:
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


async def get_file_contents(
    repo_owner: str, repo_name: str, path: str, ref: str
) -> tuple[str, str]:
    """Get a file's contents and its SHA."""
    async with GHClient() as client:
        response = await client.get(
            f"/repos/{repo_owner}/{repo_name}/contents/{path}", params={"ref": ref}
        )
        data = response.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]


async def create_or_update_file(
    repo_owner: str,
    repo_name: str,
    path: str,
    message: str,
    content: str,
    branch: str,
    sha: str | None = None,
) -> dict[str, Any]:
    """Create or update a file in a repository."""
    async with GHClient() as client:
        data = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch,
        }
        if sha:
            data["sha"] = sha

        response = await client.put(
            f"/repos/{repo_owner}/{repo_name}/contents/{path}", json=data
        )
        return response.json()


@task
async def submit_updates(
    collection_metadata: dict[str, Any],
    collection_name: str,
    branch_name: str,
    variety: CollectionViewVariety,
    repo_name: str = "prefect-collection-registry",
):
    """
    Submits updates to the collection registry.
    """
    if branch_name == "main":
        raise ValueError("Cannot submit updates directly to main!")

    metadata_file = f"views/aggregate-{variety}-metadata.json"

    # Get latest release
    latest_release = await get_latest_release("PrefectHQ", collection_name)
    if not latest_release.startswith("v"):
        latest_release = "v" + latest_release

    # Get existing metadata content
    try:
        content, sha = await get_file_contents(
            "PrefectHQ", repo_name, metadata_file, branch_name
        )
        existing_metadata_dict: dict[str, Any] = json.loads(content)
    except Exception as e:
        if "Not Found" in str(e):
            existing_metadata_dict: dict[str, Any] = {}
            sha = None
        else:
            raise

    # Update metadata
    collection_metadata_with_outer_key = {collection_name: collection_metadata}
    existing_metadata_dict.update(collection_metadata_with_outer_key)
    updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

    # Create collection version metadata file
    collection_version_path = (
        f"collections/{collection_name}/{variety}s/{latest_release}.json"
    )
    try:
        # Try to get existing file's SHA
        try:
            _, version_sha = await get_file_contents(
                "PrefectHQ", repo_name, collection_version_path, branch_name
            )
        except Exception as e:
            if "Not Found" in str(e):
                version_sha = None
            else:
                raise

        try:
            await create_or_update_file(
                "PrefectHQ",
                repo_name,
                collection_version_path,
                f"Add `{collection_name}` `{latest_release}` to {variety} records",
                json.dumps(collection_metadata_with_outer_key, indent=2),
                branch_name,
                sha=version_sha,
            )
            print(f"Added {collection_name} {latest_release} to {variety} records!")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                print(
                    f"{variety} metadata for {collection_name} {latest_release} already exists!"
                )
                return
            raise
    except Exception as e:
        if "already exists" in str(e):
            print(
                f"{variety} metadata for {collection_name} {latest_release} already exists!"
            )
            return
        raise

    # Update aggregate metadata file
    if collection_metadata:
        validate_view_content(updated_metadata_dict, variety)

        await create_or_update_file(
            "PrefectHQ",
            repo_name,
            metadata_file,
            f"Update aggregate {variety} metadata with `{collection_name}` `{latest_release}`",
            json.dumps(updated_metadata_dict, indent=2),
            branch_name,
            sha=sha,
        )
        print(
            f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
        )


async def get_file_content(url: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def get_collection_names() -> list[str]:
    repo_owner = "PrefectHQ"
    repo_name = "Prefect"
    path = "docs/integrations/catalog"

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url=f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}",
            headers={"Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        files = response.json()

    collections: list[str] = []

    async def process_file(file: dict[str, Any]):
        if file["type"] == "file" and file["name"].endswith(".yaml"):
            file_content = await get_file_content(file["download_url"])
            yaml_data = yaml.safe_load(file_content)  # type: ignore
            if yaml_data.get("author") == "Prefect":  # type: ignore
                collections.append(file["name"].replace(".yaml", ""))

    await asyncio.gather(*[process_file(file) for file in files])
    collections.append("prefect")
    return collections


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


async def get_repo_contents(
    repo_owner: str, repo_name: str, path: str, ref: str = "main"
) -> list[dict[str, Any]]:
    """Get contents of a repository path."""
    async with GHClient() as client:
        response = await client.get(
            f"/repos/{repo_owner}/{repo_name}/contents/{path}", params={"ref": ref}
        )
        return response.json()


async def get_latest_release(repo_owner: str, repo_name: str) -> str:
    """Get the latest release tag for a repository."""
    async with GHClient() as client:
        response = await client.get(f"/repos/{repo_owner}/{repo_name}/releases/latest")
        return response.json()["tag_name"]


async def get_commit_sha(repo_owner: str, repo_name: str, ref: str) -> str:
    """Get the SHA for a given ref."""
    async with GHClient() as client:
        response = await client.get(f"/repos/{repo_owner}/{repo_name}/commits/{ref}")
        return response.json()["sha"]


async def create_repo_ref(
    repo_owner: str, repo_name: str, ref: str, sha: str
) -> dict[str, Any]:
    """Create a new git reference in a repository."""
    async with GHClient() as client:
        response = await client.post(
            f"/repos/{repo_owner}/{repo_name}/git/refs", json={"ref": ref, "sha": sha}
        )
        return response.json()


async def create_pull_request(
    repo_owner: str,
    repo_name: str,
    title: str,
    body: str,
    head: str,
    base: str = "main",
) -> dict[str, Any]:
    """Create a pull request."""
    # First check if branches are different
    async with GHClient() as client:
        # Compare branches
        response = await client.get(
            f"/repos/{repo_owner}/{repo_name}/compare/{base}...{head}"
        )
        compare_data = response.json()

        if compare_data.get("ahead_by", 0) == 0:
            print(f"No difference between {base} and {head}, skipping PR creation")
            return {}

        # Create PR if there are differences
        try:
            response = await client.post(
                f"/repos/{repo_owner}/{repo_name}/pulls",
                json={
                    "title": title,
                    "body": body,
                    "head": head,
                    "base": base,
                    "maintainer_can_modify": True,
                },
            )
            return response.json()
        except httpx.HTTPStatusError as e:
            if "A pull request already exists" in str(e):
                print(f"PR from {head} to {base} already exists")
                return {}
            raise


async def get_repo(name: str) -> GitHubRepo:
    """Returns a GitHub repository object for a given collection name."""
    github_token = await Secret[str].aload("collection-registry-contents-prs-rw-pat")

    async with GHClient(token=github_token.get()) as client:
        response = await client.get(f"/repos/PrefectHQ/{name}")
        return GitHubRepo.model_validate(response.json())


def validate_view_content(
    view_dict: dict[str, Any], variety: CollectionViewVariety
) -> None:
    """Raises an error if the view content is not valid."""
    import metadata_schemas

    schema = getattr(metadata_schemas, f"{variety}_schema")
    validate = fastjsonschema.compile(schema)  # type: ignore

    for collection_name, collection_metadata in view_dict.items():
        if variety == "block":
            collection_metadata = collection_metadata["block_types"]
        try:
            # raise validation errors if any metadata doesn't match the schema
            list(map(validate, collection_metadata.values()))  # type: ignore
        except IndexError:  # to catch something like {"prefect-X": {}}
            raise ValueError("There's a key with empty value in this view!")
        print(f"  Validated {collection_name} summary in {variety} view!")


async def branch_exists(repo_owner: str, repo_name: str, branch_name: str) -> bool:
    """Check if a branch exists."""
    async with GHClient() as client:
        try:
            await client.get(f"/repos/{repo_owner}/{repo_name}/branches/{branch_name}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return False
            raise
