import inspect, json, subprocess
from collections import defaultdict
from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from pkgutil import iter_modules
from prefect import Flow, flow
from prefect.utilities.importtools import load_module
from typing import Any, Dict, Generator
from utils import get_collection_names, skip_parsing


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
        if section["kind"] in {"parameters", "raises"}:
            continue
        elif section["kind"] == "text":
            docstring_sections["summary"] = section_value
        elif section["kind"] == "returns":
            docstring_sections[section["kind"]] = "\n".join(
                return_obj.description for return_obj in section_value
            )
        elif section["kind"] == "admonition" and section_value["annotation"] == "example":

            docstring_sections["examples"].append(section_value["description"])

            
    return docstring_sections

def summarize_flow(flow: Flow, collection_name: str):
    
    install_command = f"pip install {collection_name.replace('_', '-')}"
    
    return {
        "name": flow.name,
        "parameters": dict(flow.parameters),
        "install_command": install_command,
        "description": {**parse_flow_docstring(flow)}
    }


def find_flows_in_module(
    module_name: str,
    collection_name: str = None,
) -> Generator[Flow, None, None]:
    """
    Finds all flows in a module.
    """
    module = load_module(module_name)
    
    if collection_name is None:
        collection_name = module_name

    for _, name, ispkg in iter_modules(module.__path__):
        if ispkg:
            
            yield from find_flows_in_module(f"{module_name}.{name}", collection_name)
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
                    yield obj


if __name__ == "__main__":

    flow_metadata = {}

    for collection_name in get_collection_names():
        print(f"Loading collection {collection_name}...")

        try:
            collection_module = load_module(collection_name)
        except ModuleNotFoundError:
            subprocess.run(["pip", "install", collection_name])
            collection_module = load_module(collection_name)

        collection_flow_metadata = {
            flow.name: summarize_flow(flow, collection_name)
            for flow in find_flows_in_module(collection_name)
        }
        if collection_flow_metadata:
            flow_metadata.update(
                {
                    collection_name.replace("_", "-") :
                    collection_flow_metadata
                }
            )
    with open("collections/collection_flows_metadata.json", "w") as f:
        json.dump(flow_metadata, f, indent=4)
