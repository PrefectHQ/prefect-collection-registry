import httpx
from bs4 import BeautifulSoup
from prefect.utilities.importtools import to_qualified_name
from types import ModuleType
from typing import Callable, Union

exclude_collections = {
    "prefect-ray"
}

def get_collection_names():
    catalog_resp = httpx.get("https://docs.prefect.io/collections/catalog/")
    catalog_soup = BeautifulSoup(catalog_resp.text, "html.parser")
    repo_api_urls = sorted({
        url["href"]
        .replace("https://", "https://api.github.com/repos/")
        .replace(".github.io", "")
        .rstrip("/")
        for url in catalog_soup.find_all("a", href=True)
        if ".io/prefect-" in url["href"]
    })
    return [
        i.split("/")[-1] for i in repo_api_urls
        if i.split("/")[-2] == "prefecthq"
        and i.split("/")[-1] not in exclude_collections
    ]


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