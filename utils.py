import httpx, os, re


from prefect.utilities.importtools import to_qualified_name
from types import ModuleType
from typing import Callable, Union

headers = {
    "Accept": "application/vnd.github.v3+json",
    "Authorization": f"token {os.environ['GITHUB_TOKEN']}",
}

collection_pattern = re.compile(r"^prefect-[\w\d]+$")

exclude_repos = {
    "prefect-design",
    "prefect-helm",
}


def has_release(repo_name) -> bool:
    releases_url = f"https://api.github.com/repos/PrefectHQ/{repo_name}/releases"
    response = httpx.get(releases_url, headers=headers)
    response.raise_for_status()
    return bool(response.json())


def is_not_collection_repo(repo_name):
    return not all(
        [
            collection_pattern.match(repo_name),
            repo_name not in exclude_repos,
            has_release(repo_name),
        ]
    )


def get_collection_names():

    repos_url = "https://api.github.com/orgs/PrefectHQ/repos"

    while repos_url:
        print(f"Fetching {repos_url}")
        response = httpx.get(repos_url, headers=headers)
        response.raise_for_status()
        repos = response.json()
        for repo in repos:
            if is_not_collection_repo(repo["name"]):
                continue
            yield repo["name"].replace("-", "_")
        repos_url = response.links.get("next", {}).get("url")


def skip_parsing(name: str, obj: Union[ModuleType, Callable], module_nesting: str):
    """
    Skips parsing the object if it's a private object or if it's not in the
    module nesting, preventing imports from other libraries from being added to the
    examples catalog.
    """

    try:
        wrong_module = not to_qualified_name(obj).startswith(module_nesting)
    except AttributeError:
        wrong_module = False
    return obj.__doc__ is None or name.startswith("_") or wrong_module
