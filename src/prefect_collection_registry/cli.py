import asyncio
import os
import sys
from typing import NoReturn
from uuid import UUID

from prefect import get_client
from prefect.blocks.system import Secret
from prefect.context import FlowRunContext
from prefect.results import ResultStore
from prefect.task_runners import ThreadPoolTaskRunner

from prefect_collection_registry.update_collection_metadata import (
    update_all_collections,
    update_collection_metadata,
)


async def run_single_collection(collection_name: str, branch_name: str) -> None:
    """Run metadata update for a single collection."""
    await update_collection_metadata(collection_name, branch_name)


async def run_all_collections(branch_name: str = "update-metadata") -> None:
    """Run metadata update for all collections."""
    await update_all_collections(branch_name)


def main() -> NoReturn:
    """CLI entrypoint."""
    os.environ["GITHUB_TOKEN"] = Secret.load("gh-util-token", _sync=True).get()  # type: ignore
    if len(sys.argv) == 1:
        # No args - run all collections
        asyncio.run(run_all_collections())
        sys.exit(0)
    elif len(sys.argv) in [3, 4]:
        # Two or three args - run single collection
        collection_name = sys.argv[1]
        branch_name = sys.argv[2]

        if len(sys.argv) == 4:
            # With flow run context
            flow_run_id = sys.argv[3]
            flow_run = get_client(sync_client=True).read_flow_run(UUID(flow_run_id))
            with FlowRunContext(
                flow_run=flow_run,
                client=get_client(sync_client=True),
                task_runner=ThreadPoolTaskRunner(),
                result_store=ResultStore(),
            ):
                asyncio.run(run_single_collection(collection_name, branch_name))
        else:
            # Without flow run context
            asyncio.run(run_single_collection(collection_name, branch_name))
        sys.exit(0)
    else:
        print("Usage: python -m cli [<collection_name> <branch_name> [<flow_run_id>]]")
        sys.exit(1)


if __name__ == "__main__":
    main()
