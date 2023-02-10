# Prefect Collection Registry
This is a registry of metadata for Prefect collections.

<p align="center">
    <img src=imgs/registry.png width=400>
</p>

## What metadata is stored here?
This repository stores metadata for:
- the Collections themselves
- the flows defined in those collections
- the blocks defined in those collections

## Repository Structure
This repository is structured as follows:

```
prefect-collection-registry/
|-- collections/
|   |-- collection-A/
|   |   |-- latest-release-tag-n.json
|   |   |-- flows/
|   |   |   |-- release-tag-n.json
|   |   |   |-- ...
|   |   |   |-- release-tag-0.json
|   |   |-- blocks/
|   |   |   |-- release-tag-n.json
|   |   |   |-- ...
|   |   |   |-- release-tag-0.json
|   |-- ...
|-- views/
|   |-- aggregate-block-metadata.json
|   |-- aggregate-collection-metadata.json
|   |-- aggregate-flow-metadata.json

```

## Structure of Metadata Files
Metadata files are stored in JSON format. The structure of each JSON is validated against a JSON schema.

### Flow Metadata Schema
```json
{
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "name": {
            "type": "string"
        },
        "slug": {
            "type": "string"
        },
        "parameters": {
            "type": "object"
        },
        "description": {
            "type": "object"
        },
        "documentation_url": {
            "type": "string"
        },
        "logo_url": {
            "type": "string"
        },
        "install_command": {
            "type": "string"
        },
        "path_containing_flow": {
            "type": "string"
        },
        "entrypoint": {
            "type": "string"
        },
        "repo_url": {
            "type": "string"
        }
    },
    "required": [
        "name",
        "slug",
        "parameters",
        "description",
        "documentation_url",
        "logo_url",
        "install_command",
        "path_containing_flow",
        "entrypoint",
        "repo_url"
    ],
}
```
### Block Metadata Schema
TODO

### Collection Metadata Schema
TODO


## Development
Setup a virtual environment and install the dependencies:

```bash
python3 -m venv venv
source venv/bin/activate # or your preferred method of activating a venv
pip install .
```

Run the tests:
```bash
pytest
```