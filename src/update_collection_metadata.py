import asyncio

import github3
from prefect import flow, task
from prefect.blocks.system import Secret
from prefect.deployments import run_deployment
from prefect.states import Completed

from utils import LatestReleases


@task
async def collection_needs_update(collection_name: str) -> bool:
    """
    Checks if the collection needs to be updated.
    """
    github_token = await Secret.load("github-token")
    gh = github3.login(token=github_token.get())

    collection_repo = gh.repository("PrefectHQ", collection_name)

    latest_releases = await LatestReleases.load("collections")
    latest_observed_release = latest_releases.get(collection_name)
    latest_release = collection_repo.latest_release().tag_name

    if latest_observed_release and latest_release == latest_observed_release:
        print(
            f"Collection {collection_name} is up to date! - "
            f"(latest release: {latest_release})"
        )
        return False

    latest_releases.set(collection_name, latest_release)
    await latest_releases.save("collections", overwrite=True)

    return True


@task
async def create_ref_if_not_exists(collection_name: str, branch_name: str):
    """
    Creates a reference to the latest release if it doesn't exist.
    """
    github_token = await Secret.load("github-token")
    gh = github3.login(token=github_token.get())
    repo = gh.repository("PrefectHQ", "prefect-collection-registry")

    try:
        repo.create_ref(
            ref=f"refs/heads/{branch_name}",
            sha=repo.commit(sha="main").sha,
        )
        print(f"Created ref {branch_name!r} on {repo.full_name!r}!")

    except github3.exceptions.UnprocessableEntity as e:
        if "Reference already exists" in str(e):
            print(f"Ref {branch_name!r} already exists!")
        else:
            raise


@flow(log_prints=True)
async def update_collection_metadata(
    collection_name: str, branch_name: str = "super-metadata"
):
    """
    Updates the collection metadata.
    """

    await create_ref_if_not_exists(collection_name, branch_name)

    need_update = await collection_needs_update(collection_name)

    if not need_update:
        return Completed(message=f"{collection_name} is up to date!")
    else:
        subflow_params = dict(collection_name=collection_name)
        await asyncio.gather(
            *[
                run_deployment(
                    name=f"update-{variety}-metadata/collection-{variety}",
                    parameters=subflow_params,
                )
                for variety in ["flow", "block", "package"]
            ]
        )


if __name__ == "__main__":
    asyncio.run(update_collection_metadata("prefect-airbyte"))
