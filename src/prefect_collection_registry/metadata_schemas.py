flow_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "slug": {"type": "string"},
        "parameters": {"type": "object"},
        "description": {"type": "object"},
        "documentation_url": {"type": "string"},
        "logo_url": {"type": "string"},
        "install_command": {"type": "string"},
        "path_containing_flow": {"type": "string"},
        "entrypoint": {"type": "string"},
        "repo_url": {"type": "string"},
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
        "repo_url",
    ],
}

worker_schema = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
        "type": {"type": "string"},
        "description": {"type": "string"},
        "display_name": {"type": "string"},
        "documentation_url": {"type": "string"},
        "logo_url": {"type": "string"},
        "install_command": {"type": "string"},
        "default_base_job_configuration": {"type": "object"},
        "is_beta": {"type": "boolean"},
    },
    "required": [
        "type",
        "description",
        "install_command",
        "default_base_job_configuration",
    ],
}

block_schema = {
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
