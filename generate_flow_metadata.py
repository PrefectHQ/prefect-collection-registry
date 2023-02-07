import github3, inspect, json, os, subprocess
from collections import defaultdict
from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from pkgutil import iter_modules
from prefect import Flow, flow, task
from prefect.blocks.system import Secret
from prefect.utilities.importtools import load_module
from typing import Any, Dict, Generator
from utils import skip_parsing, submit_updates

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
    return {
        "name": flow.name,
        "parameters": dict(flow.parameters),
        "install_command": f"pip install {collection_name.replace('_', '-')}",
        "description": {**parse_flow_docstring(flow)},
    }


def find_flows_in_module(
    module_name: str,
) -> Generator[Flow, None, None]:
    """
    Finds all flows in a module.
    """
    module = load_module(module_name)

    for _, name, ispkg in iter_modules(module.__path__):
        if ispkg:

            yield from find_flows_in_module(f"{module_name}.{name}")
        else:
            try:
                submodule = load_module(f"{module_name}.{name}")
                print(f"\t\tLoaded submodule {module_name}.{name}...")
            except ModuleNotFoundError:
                continue

            for _, obj in inspect.getmembers(submodule):
                if skip_parsing(name, obj, module_name):
                    continue
                if isinstance(obj, Flow):
                    yield obj


@task(log_prints=True)
def generate_flow_metadata(collection_name: str) -> Dict[str, Any]:
    """
    Generates a JSON file containing metadata about all flows in a given collection.

    Creates or updates a PR with a commit containing the updated JSON file.
    """
    subprocess.run(["pip", "install", collection_name])

    collection_slug = collection_name.replace("-", "_")

    collection_module = load_module(collection_slug)
    print(f"Loaded collection {collection_module.__name__}...")

    return {
        collection_name:
        {
            flow.name: summarize_flow(flow, collection_slug)
            for flow in find_flows_in_module(collection_slug)
        }
    }

@flow(log_prints=True)
def update_flow_metadata_for_collection(collection_name: str):
    collection_flow_metadata = generate_flow_metadata(collection_name)        
    submit_updates(collection_flow_metadata, "flows")
    
if __name__ == "__main__":
    update_flow_metadata_for_collection("prefect-airbyte")