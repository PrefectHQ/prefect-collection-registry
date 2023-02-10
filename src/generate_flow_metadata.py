from collections import defaultdict
from typing import Any, Dict

from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from jsonschema import validate
from prefect import Flow, flow, task
from prefect.utilities.importtools import load_module

from schemas import flow_schema
from utils import (
    KV,
    find_flows_in_module,
    get_collection_names,
    get_logo_url_for_collection,
    submit_updates,
)

SKIP_SECTIONS = {"parameters", "raises"}


def parse_flow_docstring(flow: Flow) -> Dict[str, Any]:
    """
    Parses the docstring of a flow.
    """
    sections = parse(Docstring(flow.description), Parser.google)

    docstring_sections = defaultdict(list)

    for section in sections:
        section = section.as_dict()
        section_value = section.get("value", [])
        if section["kind"] in SKIP_SECTIONS:
            continue
        elif section["kind"] == "text":
            docstring_sections["summary"] = section_value
        elif section["kind"] == "returns":
            docstring_sections[section["kind"]] = "\n".join(
                return_obj.description for return_obj in section_value
            )
        elif (
            section["kind"] == "admonition" and section_value["annotation"] == "example"
        ):

            docstring_sections["examples"].append(section_value["description"])

    return docstring_sections


def summarize_flow(flow: Flow, collection_name: str):

    flows_kv = KV.load("collections")

    flow_filepath = flows_kv.get_path(flow.fn.__name__)

    flow_summary = dict(
        sorted(
            {
                "name": flow.name,
                "slug": flow.fn.__name__,
                "parameters": dict(flow.parameters),
                "description": {**parse_flow_docstring(flow)},
                "documentation_url": flows_kv.get_doc_url(flow.fn.__name__),
                "logo_url": get_logo_url_for_collection(collection_name),
                "install_command": f"pip install {collection_name}",
                "path_containing_flow": flow_filepath,
                "entrypoint": f"{flow_filepath}:{flow.fn.__name__}",
                "repo_url": f"https://github.com/PrefectHQ/{collection_name}",
            }.items()
        )
    )

    validate(flow_summary, flow_schema)

    return flow_summary


@task(log_prints=True)
def generate_flow_metadata(collection_name: str) -> Dict[str, Any]:
    """
    Generates a JSON file containing metadata about all flows in a given collection.
    """
    collection_slug = collection_name.replace("-", "_")

    collection_module = load_module(collection_slug)
    print(f"Loaded collection {collection_module.__name__}...")

    return {
        collection_name: {
            flow.fn.__name__: summarize_flow(flow, collection_name)
            for flow in find_flows_in_module(collection_slug)
        }
    }


@flow(log_prints=True)
def update_flow_metadata_for_collection(collection_name: str):
    """Generates and submits flow metadata for a given collection."""
    collection_flow_metadata = generate_flow_metadata(collection_name)
    submit_updates(collection_flow_metadata, "flow")


if __name__ == "__main__":
    collection_name = "prefect-airbyte"
    for collection_name in get_collection_names():
        update_flow_metadata_for_collection(collection_name)
