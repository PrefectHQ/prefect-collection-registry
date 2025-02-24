from pathlib import Path

from pydantic_core import from_json

from prefect_collection_registry.utils import validate_view_content

EXCLUDE_TYPES = {"demo-flow"}

if __name__ == "__main__":
    for file in Path("views").glob("*.json"):
        if any(exclude in file.name for exclude in EXCLUDE_TYPES):
            continue

        print(f"validating {file} ...")

        variety = file.stem.split("-")[-2]
        view_dict = from_json(file.read_bytes())

        validate_view_content(view_dict, variety)  # type: ignore
