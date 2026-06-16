import asyncio
import os
from typing import Any

import httpx
import prefect.runtime.flow_run
from prefect import flow, task, unmapped
from prefect.artifacts import create_markdown_artifact
from prefect.states import Completed, State
from prefect.types import DateTime
from prefect.utilities.collections import listrepr
from prefect_github import GitHubCredentials

from prefect_collection_registry.generate_block_metadata import (
    update_block_metadata_for_collection,
)
from prefect_collection_registry.generate_worker_metadata import (
    update_worker_metadata_for_package,
)
from prefect_collection_registry.utils import (
    branch_exists,
    close_old_metadata_prs,
    create_pull_request,
    create_repo_ref,
    get_collection_names,
    get_commit_sha,
    get_latest_pypi_release,
    get_repo_contents,
)

# Consolidated writer PAT covering both prefect-collection-registry contents
# and pull-requests scopes. Replaces the two previous per-scope Secret blocks
# (prefect-collection-registry-contents-rw, prefect-collection-registry-prs-rw)
# as part of PLA-2840.
REGISTRY_WRITER_BLOCK = "prefect-cloud-writer"


async def _load_registry_writer_token() -> str:
    block = await GitHubCredentials.aload(REGISTRY_WRITER_BLOCK)  # type: ignore[misc]
    assert block.token
    return block.token.get_secret_value()


async def mint_prefect_contents_token() -> str:
    """Mint a short-lived (1-hour) installation token for PrefectHQ/prefect via
    the Prefect Cloud GitHub App. Authenticates with the worker's
    PREFECT_API_KEY — no long-lived GitHub credential is stored at rest.

    Replaces the prefect-contents-rw Secret block. PLA-2700.
    """
    api_url = os.environ["PREFECT_API_URL"]
    # PREFECT_API_URL is workspace-scoped; the integrations endpoint is
    # account-scoped (one level up from /workspaces/<id>).
    account_url = api_url.split("/workspaces/")[0].rstrip("/")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{account_url}/integrations/github/token",
            headers={"Authorization": f"Bearer {os.environ['PREFECT_API_KEY']}"},
            json={"owner": "PrefectHQ", "repository": "prefect"},
        )
        response.raise_for_status()
        return response.json()["token"]


TODO_COLLECTIONS = {
    "prefect-sqlalchemy",
}

UPDATE_ALL_DESCRIPTION = """
The `update_all_collections` triggers many instances of `update_collection_metadata` in order to
update the [`prefect-collection-registry`](https://github.com/PrefectHQ/prefect-collection-registry)
with metadata generated from new releases of select packages (prefect collections + prefect core).

`update_all_collections` flow will check if any packages have a release not recorded by the registry repo,
and will trigger a run of `update_collection_metadata` for each such package.
"""


async def collection_needs_update(
    collection_name: str,
    registry_contents_token: str,
    prefect_contents_token: str,
) -> tuple[str, bool]:
    """Checks if the collection needs to be updated."""
    try:
        registry_contents = await get_repo_contents(
            "PrefectHQ",
            "prefect-collection-registry",
            f"collections/{collection_name}/blocks",
            token=registry_contents_token,
            ref="main",
        )
        if not registry_contents:
            return collection_name, True

        latest_recorded_release = sorted(
            [content["name"] for content in registry_contents]
        )[-1].replace(".json", "")

        latest_release = await get_latest_pypi_release(
            collection_name, prefect_contents_token=prefect_contents_token
        )

        if latest_release == latest_recorded_release:
            print(
                f"Package {collection_name!r} is up to date! - "
                f"(latest release: {latest_release})"
            )
            return collection_name, False

        return collection_name, True

    except Exception as e:
        if "Not Found" in str(e):
            return collection_name, True
        raise


@task(name="Create Branch / PR if possible")
async def create_ref_if_not_exists(
    new_branch_name: str, registry_contents_token: str
) -> str:
    """Creates a branch if it doesn't already exist."""
    # Check if branch exists first
    if not await branch_exists(
        "PrefectHQ",
        "prefect-collection-registry",
        new_branch_name,
        token=registry_contents_token,
    ):
        main_sha = await get_commit_sha(
            "PrefectHQ",
            "prefect-collection-registry",
            "main",
            token=registry_contents_token,
        )
        await create_repo_ref(
            "PrefectHQ",
            "prefect-collection-registry",
            f"refs/heads/{new_branch_name}",
            main_sha,
            token=registry_contents_token,
        )
        print(f"Created ref {new_branch_name!r}!")
    else:
        print(f"Ref {new_branch_name!r} already exists!")

    return new_branch_name


async def update_collection_metadata(
    collection_name: str,
    branch_name: str,
) -> State:
    """Updates each variety of metadata for a given package.

    Tokens are loaded inside this entrypoint because it is invoked as a
    subprocess by `run_collection_update`, so the parent flow's already-loaded
    secrets do not survive the process boundary.
    """
    registry_contents_token = await _load_registry_writer_token()
    prefect_contents_token = await mint_prefect_contents_token()

    # Run updates sequentially to avoid conflicts in aggregate files
    await update_block_metadata_for_collection(
        collection_name,
        branch_name,
        registry_contents_token=registry_contents_token,
        prefect_contents_token=prefect_contents_token,
    )
    await update_worker_metadata_for_package(
        collection_name,
        branch_name,
        registry_contents_token=registry_contents_token,
        prefect_contents_token=prefect_contents_token,
    )

    return Completed(message=f"Successfully updated {collection_name}")


@task(log_prints=True, task_run_name="update-metadata-for-{collection_name}")
async def run_collection_update(collection_name: str, branch_name: str) -> str:
    """Run a single collection update in an isolated environment."""
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "--isolated",
        "--no-cache",
        "--upgrade",
        "--with",
        f"{collection_name}",
        "src/prefect_collection_registry/cli.py",
        collection_name,
        branch_name,
        prefect.runtime.flow_run.id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout_buffer: list[str] = []
    stderr_buffer: list[str] = []

    async def read_stream(stream: Any, buffer: list[str]) -> None:
        while line := await stream.readline():
            line = line.decode().strip()
            if line:
                buffer.append(line)

    # Read both streams concurrently
    await asyncio.gather(
        read_stream(process.stdout, stdout_buffer),
        read_stream(process.stderr, stderr_buffer),
    )

    return_code = await process.wait()

    # Format the output as markdown with headers
    output: list[str] = []
    if stdout_buffer:
        output.extend(
            [
                "## Standard Output",
                "",
                "```",
                *stdout_buffer,
                "```",
                "",
            ]
        )
    if stderr_buffer:
        output.extend(
            [
                "## Standard Error",
                "",
                "```",
                *stderr_buffer,
                "```",
                "",
            ]
        )

    if output:
        await create_markdown_artifact(  # type: ignore
            key=f"update-metadata-output-{collection_name}-{branch_name}",
            markdown="\n".join(output),
        )

    if return_code != 0:
        raise RuntimeError(f"Failed to update {collection_name}")

    return collection_name


@flow(
    name="update-all-collections",
    description=UPDATE_ALL_DESCRIPTION,
    log_prints=True,
)
async def update_all_collections(
    branch_name: str = "update-metadata",
    include_collections: list[str] | None = None,
):
    """Updates all collections for releases and updates the metadata if needed."""
    registry_writer_token = await _load_registry_writer_token()
    registry_contents_token = registry_writer_token
    registry_prs_token = registry_writer_token
    prefect_contents_token = await mint_prefect_contents_token()

    if branch_name == "update-metadata":  # avoid overwriting existing branches
        branch_name = f"update-metadata-{DateTime.now().format('MM-DD-YYYY-HH-MM-SS')}"

    # First close any old PRs before creating our new one
    await close_old_metadata_prs(
        contents_token=registry_contents_token,
        pulls_token=registry_prs_token,
    )

    # Create branch
    branch_name = await create_ref_if_not_exists(
        branch_name, registry_contents_token=registry_contents_token
    )

    collections_to_update = set(
        collection_name
        for collection_name, needs_update in await asyncio.gather(
            *[
                collection_needs_update(
                    collection_name,
                    registry_contents_token=registry_contents_token,
                    prefect_contents_token=prefect_contents_token,
                )
                for collection_name in await get_collection_names(
                    token=prefect_contents_token
                )
            ]
        )
        if needs_update
    )

    if include_collections:
        collections_to_update = collections_to_update.intersection(include_collections)

    if not collections_to_update:
        return "No new releases to record."

    print(f"Recording new release(s) for: {listrepr(collections_to_update)}...")

    # Run updates and collect results
    states = run_collection_update.map(
        collections_to_update,
        unmapped(branch_name),
        return_state=True,
    )

    succeeded_collections: set[str] = set()
    for state in states:
        try:
            collection = state.result()  # type: ignore
            succeeded_collections.add(collection)  # type: ignore
        except Exception as e:
            print(f"Failed to update collection: {e}")

    # Create PR regardless of failures - we'll mention failures in the PR description
    flow_run_url = prefect.runtime.flow_run.ui_url
    pr_description = f"Collection metadata updates are submitted to this PR by a Prefect [flow run]({flow_run_url})"
    if failed_collections := collections_to_update - succeeded_collections:
        pr_description += (
            f"\n\nNote: Updates failed for: {listrepr(failed_collections)}"
        )

    # Labelling a PR via /issues/{n}/labels needs Pull requests: R&W on a
    # fine-grained PAT (the URL says "issues" but the resource is a PR), so
    # we reuse the PRs token here rather than the issues-only one.
    await create_pull_request(
        "PrefectHQ",
        "prefect-collection-registry",
        "Update metadata for collection releases",
        pr_description,
        branch_name,
        pulls_token=registry_prs_token,
        labels=["automated-pr", "collection-metadata"],
        labels_token=registry_prs_token,
    )
    print(f"Created PR for branch {branch_name}")

    return "All new releases have been recorded."


if __name__ == "__main__":
    asyncio.run(update_all_collections(include_collections=["prefect-kubernetes"]))
