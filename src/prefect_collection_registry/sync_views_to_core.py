import asyncio
import os
from datetime import datetime

from prefect import flow
from prefect.blocks.system import Secret

from prefect_collection_registry.utils import (
    create_or_update_file,
    create_pull_request,
    create_repo_ref,
    get_commit_sha,
    get_file_contents,
)


@flow
async def sync_worker_metadata_to_core(
    source_repo_owner: str = "PrefectHQ",
    source_repo: str = "prefect-collection-registry",
    target_repo: str = "prefect",
    view_path: str = "views/aggregate-worker-metadata.json",
    target_path: str = "src/prefect/server/api/collections_data/views/aggregate-worker-metadata.json",
) -> None:
    """Syncs the worker metadata view to the Prefect core repository.
    Creates a new branch and PR if changes are detected.
    """
    # Generate unique branch name
    new_branch = f"update-worker-metadata-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Get the content from our repo
    content, _ = await get_file_contents(
        source_repo_owner, source_repo, view_path, "main"
    )

    # Create new branch in target repo
    main_sha = await get_commit_sha(source_repo_owner, target_repo, "main")
    await create_repo_ref(
        source_repo_owner,
        target_repo,
        f"refs/heads/{new_branch}",
        main_sha,
    )

    # Get the SHA of the existing file in the target repo
    try:
        _, target_file_sha = await get_file_contents(
            source_repo_owner, target_repo, target_path, new_branch
        )
    except Exception as e:
        if "Not Found" in str(e):
            target_file_sha = None
        else:
            raise

    # Update file in target repo
    await create_or_update_file(
        source_repo_owner,
        target_repo,
        target_path,
        "Update aggregate-worker-metadata.json",
        content,
        new_branch,
        sha=target_file_sha,
    )

    # Create PR
    await create_pull_request(
        source_repo_owner,
        target_repo,
        "Automated PR for Worker Metadata Update",
        "This is an automated PR to update the worker metadata.",
        new_branch,
    )


if __name__ == "__main__":
    os.environ["GITHUB_TOKEN"] = Secret.load("gh-util-token").get()  # type: ignore
    asyncio.run(sync_worker_metadata_to_core())
