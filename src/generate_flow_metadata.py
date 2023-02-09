import inspect
from collections import defaultdict
from pkgutil import iter_modules
from typing import Any, Dict, Generator

from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from jsonschema import validate
from prefect import Flow, flow, task
from prefect.utilities.importtools import load_module

from schemas import flow_schema
from utils import FlowLinks, get_logo_url_for_collection, skip_parsing, submit_updates

skip_sections = {"parameters", "raises"}


def parse_flow_docstring(flow: Flow) -> Dict[str, Any]:
    """
    Parses the docstring of a flow.
    """
    sections = parse(Docstring(flow.description), Parser.google)

    # created serialized version of each docstring section
    docstring_sections = defaultdict(list)

    for section in sections:
        section = section.as_dict()
        section_value = section.get("value", [])
        if section["kind"] in skip_sections:
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

    links = FlowLinks.load("collections")

    flow_filepath = links.get(flow.name, "path")
    flow_summary = dict(
        sorted(
            {
                "name": flow.name,
                "slug": flow.fn.__name__,
                "parameters": dict(flow.parameters),
                "description": {**parse_flow_docstring(flow)},
                "documentation_url": links.get_doc_url(flow.name),
                "logo_url": get_logo_url_for_collection(collection_name),
                "install_command": f"pip install {collection_name}",
                "path_containing_flow": flow_filepath,
                "entrypoint": f"{flow_filepath}:{flow.fn.__name__}",
                "collection_repo_url": f"https://github.com/PrefectHQ/{collection_name}",
            }.items()
        )
    )

    validate(flow_summary, flow_schema)

    return flow_summary


def find_flows_in_module(
    module_name: str,
) -> Generator[Flow, None, None]:
    """
    Finds all flows in a module.
    """
    module = load_module(module_name)

    # support loading flows from a module that is not a package
    if not hasattr(module, "__path__"):
        for _, obj in inspect.getmembers(module):
            if isinstance(obj, Flow):
                yield obj

    else:
        for _, name, ispkg in iter_modules(module.__path__):
            if ispkg:

                yield from find_flows_in_module(f"{module_name}.{name}")
            else:
                try:
                    submodule = load_module(f"{module_name}.{name}")
                    print(f"\tLoaded submodule {module_name}.{name}...")
                except ModuleNotFoundError:
                    continue

                for _, obj in inspect.getmembers(submodule):
                    if skip_parsing(name, obj, module_name):
                        continue
                    if isinstance(obj, Flow):
                        path = submodule.__name__.replace(".", "/") + ".py"
                        flow_locations = FlowLinks.load("collections")
                        flow_locations.set(obj.name, "path", path)
                        flow_locations.set(obj.name, "submodule", submodule.__name__)
                        flow_locations.save("collections", overwrite=True)
                        yield obj


@task(log_prints=True)
def generate_flow_metadata(collection_name: str) -> Dict[str, Any]:
    """
    Generates a JSON file containing metadata about all flows in a given collection.

    Creates or updates a PR with a commit containing the updated JSON file.
    """
    collection_slug = collection_name.replace("-", "_")

    collection_module = load_module(collection_slug)
    print(f"Loaded collection {collection_module.__name__}...")

    return {
        collection_name: {
            flow.name: summarize_flow(flow, collection_name)
            for flow in find_flows_in_module(collection_slug)
        }
    }


@flow(log_prints=True)
def update_flow_metadata_for_collection(collection_name: str):
    collection_flow_metadata = generate_flow_metadata(collection_name)
    submit_updates(collection_flow_metadata, "flow")


if __name__ == "__main__":
    # for collection_name in get_collection_names():
    update_flow_metadata_for_collection("prefect-airbyte")
