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
