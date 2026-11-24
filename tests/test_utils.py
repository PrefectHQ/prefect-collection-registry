import asyncio
from pathlib import Path
from typing import Any, Self

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


class TestValidateCollectionName:
    @pytest.mark.parametrize(
        "name", ["prefect", "prefect-aws", "prefect-great-expectations", "prefect-k8s"]
    )
    def test_accepts_collection_names(self, name: str):
        assert utils.validate_collection_name(name) == name

    @pytest.mark.parametrize(
        "name",
        [
            "",
            "prefect-",
            "prefect_aws",
            "prefect-AWS",
            "prefect-../../etc",
            "prefect-aws/blocks",
            "--index-url=https://example.com",
            "prefect-aws\n",
        ],
    )
    def test_rejects_other_names(self, name: str):
        with pytest.raises(ValueError, match="Invalid collection name"):
            utils.validate_collection_name(name)


class TestGetCollectionNames:
    def test_skips_directories_with_invalid_names(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        entries = [
            {"type": "dir", "name": "prefect-aws"},
            {"type": "dir", "name": "prefect-Bad_Name"},
            {"type": "dir", "name": "not-a-collection"},
            {"type": "file", "name": "prefect-readme"},
        ]

        class FakeResponse:
            def json(self) -> list[dict[str, str]]:
                return entries

        class FakeClient:
            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *exc_info: object) -> None:
                return None

            async def get(self, url: str) -> FakeResponse:
                return FakeResponse()

        monkeypatch.setattr(utils, "_gh_client", lambda token: FakeClient())

        names = asyncio.run(utils.get_collection_names(token="unused"))

        assert names == ["prefect-aws", "prefect"]
