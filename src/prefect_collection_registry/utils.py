import asyncio
import base64
import inspect
import json
import os
import tempfile
from collections.abc import Callable, Generator
from multiprocessing import Lock
from pkgutil import iter_modules
from types import ModuleType
from typing import Any, Literal

import fastjsonschema
import httpx
import yaml
from gh_util.client import GHClient
from gh_util.types import GitHubRepo
from prefect import Flow, task
from prefect.blocks.system import Secret
from prefect.utilities.importtools import load_module, to_qualified_name
from pydantic_core import from_json

CollectionViewVariety = Literal["block", "flow", "worker"]

# Create a lock file in a location accessible to all processes
LOCK_FILE = os.path.join(tempfile.gettempdir(), "prefect_collection_registry.lock")
_file_lock = Lock()


def skip_parsing(
    name: str, obj: ModuleType | Callable[..., Any], module_nesting: str
) -> bool:
    """Skips parsing the object if it's a private object or if it's not in the
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
    """Finds all flows in a module."""
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
) -> None:
    """Submits updates to the collection registry.
    Uses a multiprocessing lock to prevent concurrent modifications across processes.
    """
    if branch_name == "main":
        raise ValueError("Cannot submit updates directly to main!")

    metadata_file = f"views/aggregate-{variety}-metadata.json"

    # Get latest release
    latest_release = await get_latest_release("PrefectHQ", collection_name)
    if not latest_release.startswith("v"):
        latest_release = "v" + latest_release

    # First handle the version-specific file which can't have conflicts
    collection_version_path = (
        f"collections/{collection_name}/{variety}s/{latest_release}.json"
    )

    with _file_lock:
        # Get version file SHA
        try:
            _, version_sha = await get_file_contents(
                "PrefectHQ", repo_name, collection_version_path, branch_name
            )
        except Exception as e:
            if "Not Found" in str(e):
                version_sha = None
            else:
                raise

        # Create version-specific file
        try:
            await create_or_update_file(
                "PrefectHQ",
                repo_name,
                collection_version_path,
                f"Add `{collection_name}` `{latest_release}` to {variety} records",
                json.dumps({collection_name: collection_metadata}, indent=2),
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

    # Now handle the aggregate file with retries
    if collection_metadata:
        while True:
            with _file_lock:
                try:
                    # Get latest content and SHA
                    content, aggregate_sha = await get_file_contents(
                        "PrefectHQ", repo_name, metadata_file, branch_name
                    )
                    existing_metadata_dict: dict[str, Any] = from_json(content)
                except Exception as e:
                    if "Not Found" in str(e):
                        existing_metadata_dict = {}
                        aggregate_sha = None
                    else:
                        raise

                existing_metadata_dict[collection_name] = collection_metadata
                updated_metadata_dict = dict(sorted(existing_metadata_dict.items()))

                validate_view_content(updated_metadata_dict, variety)

                try:
                    await create_or_update_file(
                        "PrefectHQ",
                        repo_name,
                        metadata_file,
                        f"Update aggregate {variety} metadata with `{collection_name}` `{latest_release}`",
                        json.dumps(updated_metadata_dict, indent=2),
                        branch_name,
                        sha=aggregate_sha,
                    )
                    print(
                        f"Updated aggregate {variety} metadata for {collection_name} {latest_release}!"
                    )
                    return  # Success, we're done
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 409:
                        print(
                            "Conflict updating aggregate file, retrying with fresh SHA..."
                        )
                        # Release lock and try again
                        continue
                    raise


async def get_file_content(url: str) -> str:
    """Get the content of a file from a URL."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


async def get_collection_names(
    repo_owner: str = "PrefectHQ",
    repo_name: str = "Prefect",
    path: str = "docs/integrations/catalog",
) -> list[str]:
    """Get the names of all collections."""
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


def read_view_content(view: CollectionViewVariety) -> dict[str, Any]:
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
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a pull request."""
    labels = labels or []
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
            data = response.json()
            await client.post(
                f"/repos/{repo_owner}/{repo_name}/issues/{data['number']}/labels",
                json={"labels": labels},
            )
            return data
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
    from . import metadata_schemas

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


async def close_old_metadata_prs(
    repo_owner: str = "PrefectHQ",
    repo_name: str = "prefect-collection-registry",
) -> None:
    """Closes all metadata PRs except for the one associated with the latest branch.
    Also deletes all old metadata branches except the latest one.
    """
    async with GHClient() as client:
        # Get all branches to find the latest
        branches_response = await client.get(
            f"/repos/{repo_owner}/{repo_name}/branches"
        )
        metadata_branches = [
            branch["name"]
            for branch in branches_response.json()
            if branch["name"].startswith("update-metadata-")
        ]

        if not metadata_branches:
            return

        # Sort by the timestamp part of the branch name to get truly latest
        latest_branch = max(
            metadata_branches,
            key=lambda x: x.split("-", 2)[
                2
            ],  # Get the timestamp part after "update-metadata-"
        )

        # Delete all old metadata branches except latest
        for branch in metadata_branches:
            if branch != latest_branch:
                try:
                    await client.delete(
                        f"/repos/{repo_owner}/{repo_name}/git/refs/heads/{branch}"
                    )
                    print(f"Deleted branch {branch}")
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        print(f"Branch {branch} already deleted")
                    else:
                        raise

        # Get all open PRs and close them if they're for metadata branches
        response = await client.get(
            f"/repos/{repo_owner}/{repo_name}/pulls",
            params={"state": "open"},
        )

        # Close all metadata PRs except latest
        for pr in response.json():
            if (
                pr["head"]["ref"].startswith("update-metadata-")
                and pr["head"]["ref"] != latest_branch
            ):
                await client.patch(
                    f"/repos/{repo_owner}/{repo_name}/pulls/{pr['number']}",
                    json={"state": "closed"},
                )
                print(f"Closed PR #{pr['number']}: {pr['title']}")
