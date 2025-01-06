import json
from pathlib import Path

from prefect_collection_registry.utils import validate_view_content

EXCLUDE_TYPES = {"demo-flow"}

if __name__ == "__main__":
    for file in Path("views").glob("*.json"):
        if any(exclude in file.name for exclude in EXCLUDE_TYPES):
            continue

        print(f"validating {file} ...")

        variety = file.stem.split("-")[-2]
        view_dict = json.loads(file.read_text())

        validate_view_content(view_dict, variety)  # type: ignore
