from pathlib import Path
from typing import Any

import fastjsonschema
import pytest
from pydantic_core import from_json

from prefect_collection_registry import metadata_schemas, utils


@pytest.fixture
def flow_summary():
    return from_json(Path("collections/prefect-airbyte/flows/v0.2.0.json").read_bytes())


class TestFindFlowsInModule:
    @pytest.mark.xfail(reason="need to make fake collection with __path__")
    def test_finds_flows_in_module(self):
        assert len(list(utils.find_flows_in_module("test_module"))) == 2


class TestJsonSchemaValidation:
    @pytest.fixture
    def individual_flow_summary(self):
        return from_json(
            Path("collections/prefect-airbyte/flows/v0.2.0.json").read_bytes()
        )["prefect-airbyte"]["run_connection_sync"]

    def test_individual_valid_flow_schema_passes(
        self, individual_flow_summary: dict[str, Any]
    ):
        validate = fastjsonschema.compile(metadata_schemas.flow_schema)  # type: ignore

        validate(individual_flow_summary)  # type: ignore

    @pytest.mark.parametrize(
        "incorrect_kwargs", [{"name": 42}, {"slug": True}, {"parameters": "Marvin"}]
    )
    def test_individual_invalid_flow_schema_fails(
        self, individual_flow_summary: dict[str, Any], incorrect_kwargs: dict[str, Any]
    ):
        validate = fastjsonschema.compile(metadata_schemas.flow_schema)  # type: ignore

        with pytest.raises(fastjsonschema.JsonSchemaException):
            validate({**individual_flow_summary, **incorrect_kwargs})  # type: ignore
