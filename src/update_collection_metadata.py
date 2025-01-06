import asyncio
import os
from typing import Any

import httpx
from prefect import flow, task, unmapped
from prefect.artifacts import create_markdown_artifact
from prefect.blocks.system import Secret
from prefect.states import Completed, Failed, State
from prefect.types import DateTime
from prefect.utilities.collections import listrepr

import utils
from generate_block_metadata import update_block_metadata_for_collection
from generate_flow_metadata import update_flow_metadata_for_collection
from generate_worker_metadata import update_worker_metadata_for_package

UPDATE_ALL_DESCRIPTION = """
The `update_all_collections` triggers many instances of `update_collection_metadata` in order to
update the [`prefect-collection-registry`](https://github.com/PrefectHQ/prefect-collection-registry)
with metadata generated from new releases of select packages (prefect collections + prefect core).

`update_all_collections` flow will check if any packages have a release not recorded by the registry repo,
and will trigger a run of `update_collection_metadata` for each such package.
"""  # noqa


async def collection_needs_update(collection_name: str) -> tuple[str, bool]:
    """
    Checks if the collection needs to be updated.
    """
    try:
        registry_contents = await utils.get_repo_contents(
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

        latest_release = await utils.get_latest_release("PrefectHQ", collection_name)

        if collection_name == "prefect":
            latest_release = "v" + latest_release

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
async def create_ref_if_not_exists(branch_name: str) -> str:
    """Creates a branch and PR for latest releases if they don't already exist."""
    PR_TITLE = "Update metadata for collection releases"
    new_branch_name = f"{branch_name}-{DateTime.now().format('MM-DD-YYYY')}"

    # Check if branch exists first
    if not await utils.branch_exists(
        "PrefectHQ", "prefect-collection-registry", new_branch_name
    ):
        main_sha = await utils.get_commit_sha(
            "PrefectHQ", "prefect-collection-registry", "main"
        )
        await utils.create_repo_ref(
            "PrefectHQ",
            "prefect-collection-registry",
            f"refs/heads/{new_branch_name}",
            main_sha,
        )
        print(f"Created ref {new_branch_name!r}!")
    else:
        print(f"Ref {new_branch_name!r} already exists!")

    # Create PR if needed
    try:
        await utils.create_pull_request(
            "PrefectHQ",
            "prefect-collection-registry",
            PR_TITLE,
            "Collection metadata updates are submitted to this PR by a Prefect flow.",
            new_branch_name,
        )
        print(f"Created PR for {new_branch_name!r}!")
    except httpx.HTTPStatusError as e:
        response_data = e.response.json()
        if any(
            error.get("message", "").startswith("A pull request already exists")
            for error in response_data.get("errors", [])
        ):
            print(f"PR for {new_branch_name!r} already exists!")
        else:
            raise

    return new_branch_name


async def update_collection_metadata(
    collection_name: str,
    branch_name: str,
) -> State:
    """
    Updates each variety of metadata for a given package.
    """

    await update_flow_metadata_for_collection(
        collection_name=collection_name,
        branch_name=branch_name,
    )

    await update_block_metadata_for_collection(
        collection_name=collection_name,
        branch_name=branch_name,
    )

    await update_worker_metadata_for_package(
        package_name=collection_name,
        branch_name=branch_name,
    )
    return Completed(message=f"Successfully updated {collection_name}")


@task(log_prints=True, task_run_name="update-metadata-for-{collection_name}")
async def run_collection_update(
    collection_name: str, branch_name: str
) -> tuple[bool, str]:
    """Run a single collection update in an isolated environment."""
    process = await asyncio.create_subprocess_exec(
        "uv",
        "run",
        "--isolated",
        "--with",
        f"{collection_name}[dev]",
        "src/cli.py",
        collection_name,
        branch_name,
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

    return return_code == 0, collection_name


@flow(
    name="update-all-collections",
    description=UPDATE_ALL_DESCRIPTION,
    log_prints=True,
)
async def update_all_collections(
    branch_name: str = "update-metadata",
):
    """Checks all collections for releases and updates the metadata if needed."""
    branch_name = await create_ref_if_not_exists(branch_name)

    collections_to_update = [
        collection_name
        for collection_name, needs_update in await asyncio.gather(
            *[
                collection_needs_update(collection_name)
                for collection_name in await utils.get_collection_names()
            ]
        )
        if needs_update
    ]

    if not collections_to_update:
        return Completed(message="No new releases to record.")

    print(f"Recording new release(s) for: {listrepr(collections_to_update)}...")

    results = run_collection_update.map(
        [collection_name for collection_name in collections_to_update],
        unmapped(branch_name),
    ).result()

    # Check for failures
    failed_collections = [
        collection_name for succeeded, collection_name in results if not succeeded
    ]

    if failed_collections:
        return Failed(message=f"Updates failed for: {listrepr(failed_collections)}")

    return Completed(message="All new releases have been recorded.")


if __name__ == "__main__":
    os.environ["GITHUB_TOKEN"] = Secret.load("gh-util-token").get()
    asyncio.run(update_all_collections())
