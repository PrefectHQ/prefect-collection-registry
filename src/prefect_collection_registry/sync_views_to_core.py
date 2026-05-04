import asyncio
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

# Secret block names. The source repo is the registry; the target repo is
# `PrefectHQ/prefect`, and the only writes here are to the prefect repo.
REGISTRY_CONTENTS_SECRET = "prefect-collection-registry-contents-rw"
PREFECT_CONTENTS_SECRET = "prefect-contents-rw"
PREFECT_ACTIONS_SECRET = "prefect-actions-rw"


async def _load_secret(name: str) -> str:
    block = await Secret[str].aload(name)  # type: ignore[misc]
    return block.get()


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
    registry_contents_token = await _load_secret(REGISTRY_CONTENTS_SECRET)
    prefect_contents_token = await _load_secret(PREFECT_CONTENTS_SECRET)
    prefect_actions_token = await _load_secret(PREFECT_ACTIONS_SECRET)

    # Generate unique branch name
    new_branch = f"update-worker-metadata-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Get the content from our repo
    content, _ = await get_file_contents(
        source_repo_owner,
        source_repo,
        view_path,
        "main",
        token=registry_contents_token,
    )

    # Create new branch in target repo
    main_sha = await get_commit_sha(
        source_repo_owner, target_repo, "main", token=prefect_contents_token
    )
    await create_repo_ref(
        source_repo_owner,
        target_repo,
        f"refs/heads/{new_branch}",
        main_sha,
        token=prefect_contents_token,
    )

    # Get the SHA of the existing file in the target repo
    try:
        _, target_file_sha = await get_file_contents(
            source_repo_owner,
            target_repo,
            target_path,
            new_branch,
            token=prefect_contents_token,
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
        token=prefect_contents_token,
        sha=target_file_sha,
    )

    # Create PR (no labels, so no Issues token is needed)
    await create_pull_request(
        source_repo_owner,
        target_repo,
        "Automated PR for Worker Metadata Update",
        "This is an automated PR to update the worker metadata.",
        new_branch,
        pulls_token=prefect_actions_token,
    )


if __name__ == "__main__":
    asyncio.run(sync_worker_metadata_to_core())
