import fastjsonschema
import pytest

from generate_worker_metadata import generate_worker_metadata_for_package
from metadata_schemas import worker_schema


@pytest.mark.parametrize(
    "package_name,expected_worker_types",
    [
        ("prefect", {"prefect-agent", "process"}),
        ("prefect-kubernetes", {"kubernetes"}),
    ],
)
def test_generate_worker_metadata_for_package(
    package_name: str, expected_worker_types: set[str]
):
    """Tests that worker metadata is generated correctly."""
    # prefect-kubernetes is a dev dependency
    result = generate_worker_metadata_for_package(package_name)
    assert set(result.keys()) == expected_worker_types

    validate = fastjsonschema.compile(worker_schema)
    for worker_metadata in result.values():
        # will raise if metadata is invalid
        validate(worker_metadata)
