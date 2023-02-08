# Prefect Collection Registry
This is a registry of metadata for Prefect collections.

<center>
    <img src=imgs/registry.png width=500>
</center>

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
|   |-- collection-name/
|   |   |-- release-tag-n.json
|   |   |-- release-tag-0.json
|   |   ...
|-- flows/
|   |-- collection-name/
|   |   |-- release-tag-n.json
|   |   |-- release-tag-0.json
|   |   ...
|-- blocks/
|   |-- collection-name/
|   |   |-- release-tag-n.json
|   |   |-- release-tag-0.json
|   |   ...
|-- views/
|   |-- aggregate-block-metadata.json
|   |-- aggregate-collection-metadata.json
|   |-- aggregate-flow-metadata.json

```

## Structure of Metadata Files
Metadata files are stored in JSON format. The structure of each JSON for a given release is as follows:

### Block Metadata
```json
    {
        "prefect-collection-that-defines-block": {
            "block-slug": {
                "name": "Block Name",
                "slug": "block-slug",
                "logo_url": "https://images.ctfassets.net/example.png",
                "documentation_url": "https://docs.prefect.io/api-ref/prefect/blocks/...",
                "description": "A block that represents something",
                "code_example": "block code example",
                "block_schema": {
                "checksum": "sha256:...",
                "fields": {
                    "title": "Block Title",
                    "description": "A block that represents something",
                    "type": "object",
                    "properties": {
                    "value": {
                        "title": "Value",
                        "description": "A description of block attr.",
                        "type": "string",
                        "format": "date-time"
                    }
                    },
                    "required": [
                    "value"
                    ],
                    "block_type_slug": "block-slug",
                    "secret_fields": [],
                    "block_schema_references": {}
                },
                "capabilities": [],
                "version": "2.7.12"
                }
            }
        }
    }
```

### Collection Metadata
```json
{
    "collection-name": {
        "name": "collection-name",
        "author": "Prefect Technologies, Inc.",
        "latest_version": "0.2.0",
        "downloads": {
            "last_day": -1,
            "last_month": -1,
            "last_week": -1
        },
        "keywords": "prefect",
        "home_page": "https://github.com/PrefectHQ/collection-name",
        "package_url": "https://pypi.org/project/collection-name/",
        "requires_dist": [
            "prefect (>=2.0.0)",
            ...
        ],
        "requires_python": ">=3.7"
    }
}
```

### Flow Metadata
```json
{
    "prefect-collection-that-defines-flow": {
        "some-prefect-flow": {
            "name": "some-prefect-flow",
            "parameters": {
                "title": "Parameters",
                "type": "object",
                "properties": {
                    "flow_parameter": {
                        "title": "flow_parameter",
                        "description": "Description of flow parameter.",
                        "position": 0,
                        "allOf": [
                            {
                                "$ref": "#/definitions/FlowParameter"
                            }
                        ]
                    }
                },
                "required": [
                    "flow_parameter"
                ],
                "definitions": { ... Schema of flow parameter, if applicable... }
            },
            "install_command": "pip install prefect-collection",
            "description": {
                "summary": "First line of the docstring",
                "returns": "Description of the return value per docstring",
                "examples": [
                    "from prefect_collection import flow\nflow()",
                ]
            }
        }
    }
}