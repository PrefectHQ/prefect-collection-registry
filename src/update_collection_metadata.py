import asyncio
import subprocess

import github3
import pendulum
from prefect import flow, task
from prefect.deployments import run_deployment
from prefect.server.schemas.core import FlowRun
from prefect.states import Completed, Failed, State
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
    collection_repo = await utils.get_repo(collection_name)
    registry_repo = await utils.get_repo("prefect-collection-registry")
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

    latest_release = collection_repo.latest_release().tag_name

    if collection_name == "prefect":
        latest_release = "v" + latest_release

    if latest_release == latest_recorded_release:
        print(
            f"Package {collection_name!r} is up to date! - "
            f"(latest release: {latest_release})"
        )
        return collection_name, False

    return collection_name, True


@task(name="Create Branch / PR if possible")
async def create_ref_if_not_exists(branch_name: str) -> str:
    """
    Creates a branch and PR for latest releases if they don't already exist.
    """
    registry_repo = await utils.get_repo("prefect-collection-registry")
    PR_TITLE = "Update metadata for collection releases"
    new_branch_name = f"{branch_name}-{pendulum.now().format('MM-DD-YYYY')}"

    try:
        registry_repo.create_ref(
            ref=f"refs/heads/{new_branch_name}",
            sha=registry_repo.commit(sha="main").sha,
        )
        print(f"Created ref {new_branch_name!r} on {registry_repo.full_name!r}!")

    except github3.exceptions.UnprocessableEntity as e:
        if "Reference already exists" in str(e):
            print(f"Ref {new_branch_name!r} already exists!")
        else:
            raise

    if registry_repo.compare_commits("main", new_branch_name).ahead_by == 0:
        print(f"Cannot create PR - no difference between main and {new_branch_name!r}.")
        return new_branch_name

    prs = list(registry_repo.pull_requests(state="open"))

    pr_already_exists = any(
        pr.title == PR_TITLE and pr.head.ref == new_branch_name for pr in prs
    )

    if pr_already_exists:
        print(f"PR for {new_branch_name!r} already exists!")
        return new_branch_name

    new_pr = registry_repo.create_pull(
        title=PR_TITLE,
        body="Collection metadata updates are submitted to this PR by a Prefect flow.",
        head=new_branch_name,
        base="main",
        maintainer_can_modify=True,
    )

    new_pr.issue().add_labels("automated-pr", "collection-metadata")

    print(f"Created PR for {new_branch_name!r} on {registry_repo.full_name!r}!")

    return new_branch_name


@flow(log_prints=True, name="update-collection-metadata")
def update_collection_metadata(
    collection_name: str,
    branch_name: str,
) -> State:
    """
    Updates each variety of metadata for a given package.
    """

    # install the collection
    PIP_INSTALL_OUTPUT = subprocess.run(
        f"pip install -U {collection_name}[dev]".split(), stdout=subprocess.PIPE
    ).stdout.decode("utf-8")

    print(utils.pad_text(PIP_INSTALL_OUTPUT))

    update_flow_metadata_for_collection.with_options(
        flow_run_name=f"Gather / Submit FLOW metadata for {collection_name}"
    )(
        collection_name=collection_name,
        branch_name=branch_name,
    )

    update_block_metadata_for_collection.with_options(
        flow_run_name=f"Gather / Submit BLOCK metadata for {collection_name}"
    )(
        collection_name=collection_name,
        branch_name=branch_name,
    )

    update_worker_metadata_for_package.with_options(
        flow_run_name=f"Gather / Submit WORKER metadata for {collection_name}"
    )(
        package_name=collection_name,
        branch_name=branch_name,
    )
    return Completed(message=f"Successfully updated {collection_name}")


@flow(
    description=UPDATE_ALL_DESCRIPTION,
    log_prints=True,
    name="update-all-collections",
    result_storage=utils.result_storage_from_env(),
    retries=2,
    retry_delay_seconds=10,
)
async def update_all_collections(
    branch_name: str = "update-metadata",
):
    """
    Checks all collections for releases and updates the metadata if needed.
    """
    branch_name = await create_ref_if_not_exists(branch_name)

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

    print(f"Recording new release(s) for: {listrepr(collections_to_update)}...")

    subflow_runs: list[FlowRun] = await asyncio.gather(
        *[
            run_deployment(
                name="update-collection-metadata/update-a-collection",
                parameters=dict(
                    collection_name=collection_name, branch_name=branch_name
                ),
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


# if __name__ == "__main__":
    # # ALL COLLECTIONS
    # asyncio.run(update_all_collections())

    # # MANUAL RUNS
    # for collection in ["prefect-sqlalchemy"]:
    #     update_collection_metadata(collection, "update-metadata-manually")
