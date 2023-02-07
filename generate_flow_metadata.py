import github3, inspect, json, os
from collections import defaultdict
from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from pkgutil import iter_modules
from prefect import Flow, flow
from prefect.utilities.importtools import load_module
from typing import Any, Dict, Generator
from utils import skip_parsing

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

    first = True

    if first:
        first = False
        collection_name = module.__name__

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


# @flow
def generate_flow_metadata(collection_name: str):
    """
    Generates a JSON file containing metadata about all flows in a given collection.

    Creates or updates a PR with a commit containing the updated JSON file.
    """
    collection_slug = collection_name.replace("-", "_")
    flow_metadata_file = "flows/collection_flows_metadata.json"
    BRANCH_NAME = "flow-metadata"

    # read the existing flow metadata from existing JSON file
    # within the collection repo
    gh = github3.login(token=os.getenv("GITHUB_TOKEN"))

    prefect_core_repo = gh.repository("PrefectHQ", "prefect")
    registry_repo = gh.repository("PrefectHQ", "prefect-collection-registry")
    collection_repo = gh.repository("PrefectHQ", f"{collection_name}")
    latest_release = collection_repo.latest_release().tag_name

    print(f"found {collection_repo} {latest_release}")

    flow_metadata_raw = registry_repo.file_contents(
        flow_metadata_file, ref="flow-metadata"
    ).decoded.decode()

    # make a dict of the existing flow metadata
    flow_metadata = json.loads(flow_metadata_raw)

    collection_module = load_module(collection_slug)

    print(f"Loaded collection {collection_module.__name__}...")

    collection_flow_metadata = {
        flow.name: summarize_flow(flow, collection_slug)
        for flow in find_flows_in_module(collection_slug)
    }
    if collection_flow_metadata:
        flow_metadata.update({collection_name: collection_flow_metadata})
    
        # create a new commit with the updated flow metadata
        registry_repo.file_contents(
            flow_metadata_file, ref=BRANCH_NAME
        ).update(
            message=f"Update flow metadata for {collection_name} {latest_release}",
            content=json.dumps(flow_metadata, indent=4).encode("utf-8"),
            branch=BRANCH_NAME,
        )

if __name__ == "__main__":
    generate_flow_metadata("prefect-airbyte")
