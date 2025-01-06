from collections import defaultdict
from typing import Any, Callable

import fastjsonschema
from griffe import Docstring, DocstringSectionKind, Parser, parse
from prefect import Flow, flow, task
from prefect.states import Completed
from prefect.utilities.importtools import load_module

from prefect_collection_registry.metadata_schemas import flow_schema
from prefect_collection_registry.utils import (
    find_flows_in_module,
    get_logo_url_for_collection,
    submit_updates,
)

SKIP_DOCSTRING_SECTIONS = {"parameters", "raises"}


def get_code_examples(obj: Callable[..., Any]) -> list[str]:
    """
    Gathers all code examples within a callable that has a Google style docstring.
    """
    code_examples: set[str] = set()
    docstring = Docstring(obj.__doc__ or "")
    parsed_sections = parse(docstring, Parser.google)

    for section in parsed_sections:
        if section.kind == DocstringSectionKind.examples:
            code_example = "\n".join(
                (part[1] for part in section.as_dict().get("value", []))
            )
            code_examples.add(code_example)
        if section.kind == DocstringSectionKind.admonition:
            value = section.as_dict().get("value", {})
            if value.get("annotation") == "example":
                code_examples.add(value.get("description"))

    return list(code_examples)


def parse_flow_docstring(flow: Flow[..., Any]) -> dict[str, Any]:
    """
    Parses the docstring of a flow.
    """
    sections = parse(Docstring(flow.description or ""), Parser.google)

    docstring_sections: defaultdict[str, Any] = defaultdict(list)

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
    docstring_sections["examples"] = get_code_examples(flow)

    return docstring_sections


def get_doc_url(flow: Flow[..., Any]) -> str:
    return (
        "https://prefecthq.github.io/"
        f"{flow.fn.__module__.replace('.', '/').replace('_', '-')}/"
        f"#{flow.fn.__module__}."
        f"{flow.fn.__name__}"
    )


def summarize_flow(flow: Flow[..., Any], collection_name: str) -> dict[str, Any]:
    """Generates a summary of a flow that should match the flow JSON schema,
    and validates it against the schema.
    """

    flow_filepath = f"{flow.fn.__module__.replace('.', '/')}.py"

    flow_summary: dict[str, Any] = dict(
        sorted(
            {  # type: ignore
                "name": flow.name,
                "slug": flow.fn.__name__,
                "parameters": dict(flow.parameters),
                "description": {**parse_flow_docstring(flow)},
                "documentation_url": get_doc_url(flow),
                "logo_url": get_logo_url_for_collection(collection_name),
                "install_command": f"pip install {collection_name}",
                "path_containing_flow": flow_filepath,
                "entrypoint": f"{flow_filepath}:{flow.fn.__name__}",
                "repo_url": f"https://github.com/PrefectHQ/{collection_name}",
            }.items()
        )
    )
    validate = fastjsonschema.compile(flow_schema)  # type: ignore
    validate(flow_summary)  # type: ignore
    return flow_summary


@task
def generate_flow_metadata(collection_name: str) -> dict[str, Any]:
    """
    Generates a JSON file containing metadata about all flows in a given collection.
    """
    collection_slug = collection_name.replace("-", "_")

    collection_module = load_module(collection_slug)
    print(f"Loaded collection {collection_module.__name__}...")

    return {
        flow.fn.__name__: summarize_flow(flow, collection_name)
        for flow in find_flows_in_module(collection_slug)
    }


@flow(name="update-flow-metadata-for-collection")
async def update_flow_metadata_for_collection(collection_name: str, branch_name: str):
    """Generates and submits flow metadata for a given collection."""
    if collection_name == "prefect":
        return Completed(message="No flow metadata to update for Prefect core.")

    collection_flow_metadata = generate_flow_metadata(collection_name)
    await submit_updates(
        collection_metadata=collection_flow_metadata,
        collection_name=collection_name,
        branch_name=branch_name,
        variety="flow",
    )
