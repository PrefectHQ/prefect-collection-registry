import os
import sys

from prefect import Flow
from prefect.utilities.importtools import load_module

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


from src.generate_flow_metadata import find_flows_in_module


class TestGenerateFlowMetadata:
    def test_find_flows_in_module(self):

        majewel = load_module("prefect_airbyte")

        flow = list(find_flows_in_module(majewel.__name__))[0]

        assert isinstance(flow, Flow)
        assert flow.name == "run-connection-sync"
        assert flow.fn.__name__ == "run_connection_sync"
        assert flow.fn.__module__ == "prefect_airbyte.flows"
