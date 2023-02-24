import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import fastjsonschema
import pytest

from src import metadata_schemas, utils


@pytest.fixture
def flow_summary():
    content = Path("collections/prefect-airbyte/flows/v0.2.0.json").read_text()
    return json.loads(content)


class TestFindFlowsInModule:
    @pytest.mark.xfail(reason="need to make fake collection with __path__")
    def test_finds_flows_in_module(self):
        assert len(list(utils.find_flows_in_module("test_module"))) == 2


class TestJsonSchemaValidation:
    @pytest.fixture
    def individual_flow_summary(self):
        content = Path("collections/prefect-airbyte/flows/v0.2.0.json").read_text()
        return json.loads(content)["prefect-airbyte"]["run_connection_sync"]

    def test_individual_valid_flow_schema_passes(self, individual_flow_summary):
        validate = fastjsonschema.compile(metadata_schemas.flow_schema)

        validate(individual_flow_summary)

    @pytest.mark.parametrize(
        "incorrect_kwargs", [{"name": 42}, {"slug": True}, {"parameters": "Marvin"}]
    )
    def test_individual_invalid_flow_schema_fails(
        self, individual_flow_summary, incorrect_kwargs
    ):
        validate = fastjsonschema.compile(metadata_schemas.flow_schema)

        with pytest.raises(fastjsonschema.JsonSchemaException):
            validate({**individual_flow_summary, **incorrect_kwargs})
