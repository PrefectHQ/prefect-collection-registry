import asyncio
import subprocess

import github3
import pendulum
from prefect import flow, task
from prefect.blocks.system import Secret
from prefect.deployments import run_deployment
from prefect.server.schemas.core import FlowRun
from prefect.states import Completed, Failed, State
from prefect.utilities.collections import listrepr

import utils
from generate_block_metadata import update_block_metadata_for_collection
from generate_flow_metadata import update_flow_metadata_for_collection


async def collection_needs_update(
    collection_name: str, github_token_name: str = "collection-registry-github-token"
) -> tuple[str, bool]:
    """
    Checks if the collection needs to be updated.
    """
    github_token = await Secret.load(github_token_name)
    gh = github3.login(token=github_token.get())

    collection_repo = gh.repository("PrefectHQ", collection_name)
    registry_repo = gh.repository("PrefectHQ", "prefect-collection-registry")
    try:
        latest_recorded_release = sorted(
            [
                name
                for name, _ in registry_repo.directory_contents(
                    directory_path=f"collections/{collection_name}/blocks", ref="main"
                )
            ]
        )[-1].replace(".json", "")
    except github3.exceptions.NotFoundError:
        return collection_name, True

    latest_release = collection_repo.latest_release().tag_name.replace("v", "")

    if latest_release == latest_recorded_release:
        print(
            f"Collection {collection_name} is up to date! - "
            f"(latest release: {latest_release})"
        )
        return collection_name, False

    return collection_name, True


@task
async def create_ref_if_not_exists(
    branch_name: str, github_token_name: str = "collection-registry-github-token"
) -> str:
    """
    Creates a branch and PR for latest releases if they don't already exist.
    """
    github_token = await Secret.load(github_token_name)
    gh = github3.login(token=github_token.get())
    repo = gh.repository("PrefectHQ", "prefect-collection-registry")
    PR_TITLE = "Update metadata for collection releases"
    new_branch_name = f"{branch_name}-{pendulum.now().format('MM-DD-YYYY')}"

    try:
        repo.create_ref(
            ref=f"refs/heads/{new_branch_name}",
            sha=repo.commit(sha="main").sha,
        )
        print(f"Created ref {new_branch_name!r} on {repo.full_name!r}!")

    except github3.exceptions.UnprocessableEntity as e:
        if "Reference already exists" in str(e):
            print(f"Ref {new_branch_name!r} already exists!")
        else:
            raise

    if repo.compare_commits("main", new_branch_name).ahead_by == 0:
        print(f"Cannot create PR - no difference between main and {new_branch_name!r}.")
        return new_branch_name

    prs = list(repo.pull_requests(state="open"))

    pr_already_exists = any(
        pr.title == PR_TITLE and pr.head.ref == new_branch_name for pr in prs
    )

    if pr_already_exists:
        print(f"PR for {new_branch_name!r} already exists!")
        return new_branch_name

    new_pr = repo.create_pull(
        title=PR_TITLE,
        body="Collection metadata updates are submitted to this PR by a Prefect flow.",
        head=new_branch_name,
        base="main",
        maintainer_can_modify=True,
    )

    new_pr.issue().add_labels("automated-pr", "collection-metadata")

    print(f"Created PR for {new_branch_name!r} on {repo.full_name!r}!")

    return new_branch_name


# create a deployment for this with
# prefect deployment build update_collection_metadata.py:update_collection_metadata -n collections-updates ... -a
@flow
def update_collection_metadata(
    collection_name: str,
    branch_name: str = "update-metadata",
) -> State:
    """
    Updates each variety of metadata for a given package.
    """

    # install the collection
    subprocess.run(f"pip install -U {collection_name}".split())

    update_flow_metadata_for_collection(collection_name, branch_name)

    update_block_metadata_for_collection(collection_name, branch_name)

    return Completed(message=f"Successfully updated {collection_name}")


@flow(log_prints=True)
async def update_all_collections(
    branch_name: str = "update-metadata",
):
    """
    Checks all collections for releases and updates the metadata if needed.
    """
    await create_ref_if_not_exists(branch_name)

    collections_to_update = [
        collection_name
        for collection_name, needs_update in await asyncio.gather(
            *[
                collection_needs_update(collection_name)
                for collection_name in utils.get_collection_names()
            ]
        )
        if needs_update
    ]

    if not collections_to_update:
        return Completed(message="No new releases to record.")

    print(f"Recording new releases for: {listrepr(collections_to_update)}...")

    subflow_runs: list[FlowRun] = await asyncio.gather(
        *[
            run_deployment(
                name="update-collection-metadata/collection-updates",
                parameters=dict(collection_name=collection_name),
                flow_run_name=f"update-{collection_name}-{str(pendulum.now())}",
            )
            for collection_name in collections_to_update
        ]
    )

    if failed_subflow_runs := [
        run.name for run in subflow_runs if run.state.is_failed()
    ]:
        return Failed(message=f"Some subflows failed: {listrepr(failed_subflow_runs)} ")

    return Completed(message="All new releases have been recorded.")
