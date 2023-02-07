import github3, inspect, json, os, subprocess
from collections import defaultdict
from griffe.dataclasses import Docstring
from griffe.docstrings.parsers import Parser, parse
from pkgutil import iter_modules
from prefect import Flow, flow, task
from prefect.utilities.importtools import load_module
from typing import Any, Dict, Generator
from utils import get_collection_names, skip_parsing

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
def generate_flow_metadata(collection_name: str):
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

@task
def submit_updates(collection_flow_metadata: dict):

    collection_name = list(collection_flow_metadata.keys())[0]
    flow_metadata_file = "views/aggregate-flow-metadata.json"
    REPO_NAME = "prefect-collection-registry"
    BRANCH_NAME = "flow-metadata"

    # read the existing flow metadata from existing JSON file
    gh = github3.login(token=os.getenv("GITHUB_TOKEN"))
    repo = gh.repository("PrefectHQ", REPO_NAME)

    existing_flow_metadata_raw = repo.file_contents(
        flow_metadata_file, ref=BRANCH_NAME
    ).decoded.decode()

    flow_metadata_dict = json.loads(existing_flow_metadata_raw)
    
    collection_repo = gh.repository("PrefectHQ", f"{collection_name}")
    latest_release = collection_repo.latest_release().tag_name
    
    flow_metadata_dict.update(collection_flow_metadata)
        
    # create a new commit adding the collection version metadata
    try:
        repo.create_file(
            path=f"flows/{collection_name}/{latest_release}.json",
            message=f"Add {collection_name} {latest_release} to flow records",
            content=json.dumps(collection_flow_metadata, indent=4).encode("utf-8"),
            branch=BRANCH_NAME,
        )
    except github3.exceptions.UnprocessableEntity as e:
        # file already exists so nothing to do
        if "\"sha\" wasn't supplied" in str(e):
            print(f"Flow metadata for {collection_name} {latest_release} already exists!")
            return
        raise
    
    # create a new commit updating the aggregate flow metadata file
    repo.file_contents(flow_metadata_file, ref=BRANCH_NAME).update(
        message=f"Update aggregate flow metadata with {collection_name} {latest_release}",
        content=json.dumps(flow_metadata_dict, indent=4).encode("utf-8"),
        branch=BRANCH_NAME,
    )

    print(f"Updated flow metadata for {collection_name} {latest_release}!")

@flow(log_prints=True)
def update_flow_metadata_for_collection(collection_name: str):
    collection_flow_metadata = generate_flow_metadata(collection_name)        
    submit_updates(collection_flow_metadata)

if __name__ == "__main__":
    for collection_name in get_collection_names():
        update_flow_metadata_for_collection(collection_name)