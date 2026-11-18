import fastjsonschema
import prefect_github  # noqa: F401

from prefect_collection_registry.generate_block_metadata import (
    generate_prefect_block_metadata,
)
from prefect_collection_registry.metadata_schemas import block_schema


def test_prefect_block_metadata_excludes_collection_blocks():
    """Blocks from an imported collection are not listed as prefect blocks.

    `update_collection_metadata` imports prefect_github to load its token
    before it generates metadata, which adds GitHubCredentials and
    GitHubRepository to prefect's block registry.
    """
    result = generate_prefect_block_metadata()["block_types"]

    assert "secret" in result
    assert "github-credentials" not in result
    assert "github-repository" not in result

    validate = fastjsonschema.compile(block_schema)  # type: ignore
    for block_metadata in result.values():
        # will raise if metadata is invalid
        validate(block_metadata)  # type: ignore
