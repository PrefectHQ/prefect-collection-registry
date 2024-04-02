import asyncio
import subprocess

import pendulum
import utils
from generate_block_metadata import update_block_metadata_for_collection
from generate_flow_metadata import update_flow_metadata_for_collection
from generate_worker_metadata import update_worker_metadata_for_package
from prefect import flow
from prefect.client.schemas.objects import FlowRun
from prefect.deployments import run_deployment
from prefect.states import Completed, Failed, State
from prefect.utilities.collections import listrepr

UPDATE_ALL_DESCRIPTION = """
The `update_all_collections` triggers many instances of `update_collection_metadata` in order to
update the [`prefect-collection-registry`](https://github.com/PrefectHQ/prefect-collection-registry)
with metadata generated from new releases of select packages (prefect collections + prefect core).

`update_all_collections` flow will check if any packages have a release not recorded by the registry repo,
and will trigger a run of `update_collection_metadata` for each such package.
"""  # noqa


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
    retries=2,
    retry_delay_seconds=10,
)
async def update_all_collections(
    branch_name: str | None = None,
):
    """
    Checks all collections for releases and updates the metadata if needed.
    """

    if branch_name is None:
        branch_name = f"update-metadata-{pendulum.now().strftime('%Y-%m-%d')}"

    if not (collections_to_update := await utils.get_collections_to_update()):
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
