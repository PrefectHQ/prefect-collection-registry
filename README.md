# Prefect Collection Registry
This is a registry of metadata for Prefect collections.

<p align="center">
    <img src=imgs/registry.png width=400>
</p>

## What metadata is stored here?
This repository stores metadata for:
- the flows defined in collections
- the blocks defined in collections and prefect core

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
|   |-- ...

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
```json
{
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "logo_url": {
            "minLength": 1,
            "maxLength": 2083,
            "format": "uri",
            "type": "string",
        },
        "documentation_url": {
            "minLength": 1,
            "maxLength": 2083,
            "format": "uri",
            "oneOf": [{"type": "string"}, {"type": "null"}],
        },
        "description": {"type": "string"},
        "code_example": {"type": "string"},
        "block_schema": {"$ref": "#/components/schemas/block_schema"},
    },
    "required": [
        "name",
        "slug",
        "logo_url",
        "description",
        "code_example",
        "block_schema",
    ],
    "components": {
        "schemas": {
            "block_schema": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "checksum": {"type": "string"},
                    "version": {"type": "string"},
                    "capabilities": {"type": "array", "items": {"type": "string"}},
                    "fields": {"type": "object"},
                },
                "required": [
                    "checksum",
                    "version",
                    "capabilities",
                    "fields",
                ],
            }
        }
    },
}
```

### Worker Metadata Schema
```json
{
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "description": {"type": "string"},
        "documentation_url": {"type": "string"},
        "logo_url": {"type": "string"},
        "install_command": {"type": "string"},
        "default_base_job_configuration": {"type": "object"},
    },
    "required": [
        "type",
        "description",
        "install_command",
        "default_base_job_configuration",
    ],
}
```

## Development
Requires Python 3.10+

Setup a virtual environment and install the dependencies:

```bash
python3 -m venv venv
source venv/bin/activate # or your preferred method of activating a venv
pip install ".[dev]"
```

Run the tests:
```bash
coverage run --branch -m pytest tests -vv
```