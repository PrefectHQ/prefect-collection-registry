# prefect-collection-registry
This is a registry of metadata for Prefect collections.

<p align="center">
    <img src=imgs/registry.png width=400>
</p>

## what metadata is stored here?
This repository stores metadata for:
- the flows defined in collections
- the blocks defined in collections and prefect core

## repository structure
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

## structure of metadata files
Metadata files are stored in JSON format. The structure of each JSON is validated against a JSON schema.

### flow metadata schema
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
### block metadata schema
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

### worker metadata schema
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

## development
requires `uv` for dependency management and virtual environments.

if you don't have `uv`, install it:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Setup the development environment:
```bash
uv sync --dev --all-extras
```

Install and run pre-commit hooks:
```bash
uv run pre-commit install
uv run pre-commit run --all-files --show-diff-on-failure
```

The pre-commit hooks will:
- Run Ruff for linting and formatting
- Validate JSON schema files

Run the tests:
```bash
uv run --with-editable '.[dev]' pytest tests -vv
```

### notes for maintainers

#### deploy the metadata update flow
```
uv run prefect --no-prompt deploy --all
```


#### run the metadata update script interactively

this is the main entrypoint flow for updating all collections
```bash
uv run --frozen src/prefect_collection_registry/update_collection_metadata.py
```

this will:
- discover collections we need to update (have been released but not recorded in this repo)
- discover and commit the metadata (see schemas above) for those collections
  - update the flow metadata
  - update the block metadata
  - update the worker metadata
- create or update a PR with these changes

#### run the worker metadata sync script interactively

> [!NOTE]
> Though this script is automatically run on merge to `main`, you may also want to run it manually if something goes wrong.

this is the main entrypoint flow for syncing worker metadata to prefect core
```bash
uv run --frozen src/prefect_collection_registry/sync_views_to_core.py
```

this will:
- get the current worker metadata from this repo
- create a new branch in the prefect core repo
- commit the worker metadata to the new branch
- create a PR with these changes
