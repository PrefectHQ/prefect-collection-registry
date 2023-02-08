import os
import sys

from prefect import Flow
from prefect.utilities.importtools import load_module

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest

from src import generate_flow_metadata


class TestGenerateFlowMetadata:
    @pytest.mark.parametrize(
        "module_name, expected_flows",
        [
            ("test_module", ["foo", "bar"]),
            ("prefect_airbyte", ["run-connection-sync"]),
        ],
    )
    def test_find_flows_in_module(self, module_name, expected_flows):

        majewel = load_module(module_name)

        flows = {
            flow.name: flow
            for flow in list(
                generate_flow_metadata.find_flows_in_module(majewel.__name__)
            )
        }

        assert list(flows.keys()) == sorted(expected_flows)
        assert all(isinstance(flow, Flow) for flow in flows.values())
