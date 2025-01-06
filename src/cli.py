import asyncio
import sys
from typing import NoReturn

from update_collection_metadata import (
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
    if len(sys.argv) == 1:
        # No args - run all collections
        asyncio.run(run_all_collections())
        sys.exit(0)
    elif len(sys.argv) == 3:
        # Two args - run single collection
        collection_name, branch_name = sys.argv[1:]
        asyncio.run(run_single_collection(collection_name, branch_name))
        sys.exit(0)
    else:
        print("Usage: python -m cli [<collection_name> <branch_name>]")
        sys.exit(1)


if __name__ == "__main__":
    main()
