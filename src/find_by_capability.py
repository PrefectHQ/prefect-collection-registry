import json
import sys
from pathlib import Path


def find_by_capability(desired: set[str]) -> list[tuple[str, str]]:
    for file in Path().glob('collections/*/blocks/*.json'):
        collection_name = file.parts[-3]
        version = file.stem
        collection = json.loads(file.read_text())
        blocks = collection.get('block_types') or {}
        for block_slug, block_info in blocks.items():
            if 'block_schema' not in block_info:
                continue
            capabilities = set(block_info['block_schema']['capabilities'])
            if capabilities.intersection(desired):
                print(f"{collection_name}:{version}:{block_slug}")


if __name__ == "__main__":
    find_by_capability(set(sys.argv[1:]))
