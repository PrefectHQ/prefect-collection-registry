import asyncio
import os
from typing import Any, cast

import prefect.runtime.flow_run
from prefect import flow, task, unmapped
from prefect.artifacts import create_markdown_artifact
from prefect.blocks.system import Secret
from prefect.futures import PrefectFutureList
from prefect.states import Completed, Failed, State
from prefect.types import DateTime
from prefect.utilities.collections import listrepr

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

UPDATE_ALL_DESCRIPTION = """
The `update_all_collections` triggers many instances of `update_collection_metadata` in order to
update the [`prefect-collection-registry`](https://github.com/PrefectHQ/prefect-collection-registry)
with metadata generated from new releases of select packages (prefect collections + prefect core).

`update_all_collections` flow will check if any packages have a release not recorded by the registry repo,
and will trigger a run of `update_collection_metadata` for each such package.
"""


async def collection_needs_update(collection_name: str) -> tuple[str, bool]:
    """Checks if the collection needs to be updated."""
    try:
        registry_contents = await get_repo_contents(
            "PrefectHQ",
            "prefect-collection-registry",
            f"collections/{collection_name}/blocks",
            ref="main",
        )
        if not registry_contents:
            return collection_name, True

        latest_recorded_release = sorted(
            [content["name"] for content in registry_contents]
        )[-1].replace(".json", "")

        latest_release = await get_latest_pypi_release(collection_name)

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
async def create_ref_if_not_exists(new_branch_name: str) -> str:
    """Creates a branch if it doesn't already exist."""
    # Check if branch exists first
    if not await branch_exists(
        "PrefectHQ", "prefect-collection-registry", new_branch_name
    ):
        main_sha = await get_commit_sha(
            "PrefectHQ", "prefect-collection-registry", "main"
        )
        await create_repo_ref(
            "PrefectHQ",
            "prefect-collection-registry",
            f"refs/heads/{new_branch_name}",
            main_sha,
        )
        print(f"Created ref {new_branch_name!r}!")
    else:
        print(f"Ref {new_branch_name!r} already exists!")

    return new_branch_name


async def update_collection_metadata(
    collection_name: str,
    branch_name: str,
) -> State:
    """Updates each variety of metadata for a given package."""
    # Run updates sequentially to avoid conflicts in aggregate files
    await update_block_metadata_for_collection(collection_name, branch_name)
    await update_worker_metadata_for_package(collection_name, branch_name)

    return Completed(message=f"Successfully updated {collection_name}")


@task(log_prints=True, task_run_name="update-metadata-for-{collection_name}")
async def run_collection_update(collection_name: str, branch_name: str) -> str:
    """Run a single collection update in an isolated environment."""
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "--isolated",
        "--with",
        f"{collection_name}[dev]",
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
):
    """Updates all collections for releases and updates the metadata if needed."""
    os.environ["GITHUB_TOKEN"] = (await Secret.aload("gh-util-token")).get()  # type: ignore

    if branch_name == "update-metadata":  # avoid overwriting existing branches
        branch_name = f"update-metadata-{DateTime.now().format('MM-DD-YYYY-HH-MM-SS')}"

    # First close any old PRs before creating our new one
    await close_old_metadata_prs()

    # Create branch
    branch_name = await create_ref_if_not_exists(branch_name)

    collections_to_update = set(
        collection_name
        for collection_name, needs_update in await asyncio.gather(
            *[
                collection_needs_update(collection_name)
                for collection_name in await get_collection_names()
            ]
        )
        if needs_update
    )

    if not collections_to_update:
        return Completed(message="No new releases to record.")

    print(f"Recording new release(s) for: {listrepr(collections_to_update)}...")

    # Run updates and collect results
    futures = run_collection_update.map(
        collections_to_update,
        unmapped(branch_name),
    )

    succeeded_collections: set[str] = set()
    for future in cast(PrefectFutureList[str], futures):
        try:
            collection = future.result()
            succeeded_collections.add(collection)
        except Exception as e:
            print(f"Failed to update collection: {e}")

    # Create PR regardless of failures - we'll mention failures in the PR description
    flow_run_url = prefect.runtime.flow_run.ui_url
    pr_description = f"Collection metadata updates are submitted to this PR by a Prefect [flow run]({flow_run_url})"
    if failed_collections := collections_to_update - succeeded_collections:
        pr_description += (
            f"\n\nNote: Updates failed for: {listrepr(failed_collections)}"
        )

    await create_pull_request(
        "PrefectHQ",
        "prefect-collection-registry",
        "Update metadata for collection releases",
        pr_description,
        branch_name,
        labels=["automated-pr", "collection-metadata"],
    )
    print(f"Created PR for branch {branch_name}")

    # Now we can return the appropriate state
    if failed_collections:
        return Failed(message=f"Updates failed for: {listrepr(failed_collections)}")  # type: ignore
    return Completed(message="All new releases have been recorded.")


if __name__ == "__main__":
    # manually run one or many collections
    asyncio.run(
        update_collection_metadata(
            "prefect-kubernetes", "update-metadata-02-24-2025-21-02-80"
        )
    )

    # asyncio.run(update_all_collections())
