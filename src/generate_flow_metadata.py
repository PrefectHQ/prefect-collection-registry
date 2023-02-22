from collections import defaultdict
from typing import Any, Dict

import fastjsonschema
from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from prefect import Flow, flow, task
from prefect.states import Completed
from prefect.utilities.importtools import load_module

import utils
from metadata_schemas import flow_schema

SKIP_DOCSTRING_SECTIONS = {"parameters", "raises"}


def parse_flow_docstring(flow: Flow) -> Dict[str, Any]:
    """
    Parses the docstring of a flow.
    """
    sections = parse(Docstring(flow.description), Parser.google)

    docstring_sections = defaultdict(list)

    for section in sections:
        section = section.as_dict()
        section_value = section.get("value", [])
        if section["kind"] in SKIP_DOCSTRING_SECTIONS:
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


def get_doc_url(flow: Flow) -> str:
    return (
        "https://prefecthq.github.io/"
        f"{flow.fn.__module__.replace('.', '/').replace('_', '-')}/"
        f"#{flow.fn.__module__}."
        f"{flow.fn.__name__}"
    )


def summarize_flow(flow: Flow, collection_name: str) -> Dict[str, Any]:
    """Generates a summary of a flow that should match the flow JSON schema,
    and validates it against the schema.
    """

    flow_filepath = f"{flow.fn.__module__.replace('.', '/')}.py"

    flow_summary = dict(
        sorted(
            {
                "name": flow.name,
                "slug": flow.fn.__name__,
                "parameters": dict(flow.parameters),
                "description": {**parse_flow_docstring(flow)},
                "documentation_url": get_doc_url(flow),
                "logo_url": utils.get_logo_url_for_collection(collection_name),
                "install_command": f"pip install {collection_name}",
                "path_containing_flow": flow_filepath,
                "entrypoint": f"{flow_filepath}:{flow.fn.__name__}",
                "repo_url": f"https://github.com/PrefectHQ/{collection_name}",
            }.items()
        )
    )
    validate = fastjsonschema.compile(flow_schema)
    validate(flow_summary)
    return flow_summary


@task
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
            for flow in utils.find_flows_in_module(collection_slug)
        }
    }


@flow
def update_flow_metadata_for_collection(collection_name: str, branch_name: str):
    """Generates and submits flow metadata for a given collection."""
    if collection_name == "prefect":
        return Completed(message="No flow metadata to update for Prefect core.")

    collection_flow_metadata = generate_flow_metadata(collection_name)
    utils.submit_updates(
        collection_metadata=collection_flow_metadata,
        collection_name=collection_name,
        branch_name=branch_name,
        variety="flow",
    )
