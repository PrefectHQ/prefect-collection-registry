import asyncio
import re

from prefect.blocks.core import Block
from prefect.server.api.collections import get_collection_view

from utils import get_repo

GITHUB_TOKEN = Block.load("secret/collection-registry-contents-prs-rw-pat").get()

async def get_correct_logo_urls() -> dict[str, dict[str, str]]:
    """Returns a dictionary of block types and their logo urls.
    
    Structure of the dictionary:
    {
        "collection_name": {
            "block_name": "logo_url"
        }
    }
    
    """
    agg_view = await get_collection_view("aggregate-block-metadata")
    
    result = {}
    for collection_name, collection_details in agg_view.items():
        result[collection_name] = {
            block_name: block_details['logo_url']
            for block_name, block_details in collection_details['block_types'].items()
        }

    return result

async def process_repos(repos, correct_urls):
    for repo_name in repos:
        repo = await get_repo(repo_name)
        await process_directory(repo, "/", correct_urls, repo_name)

async def process_directory(repo, directory_path, correct_urls, repo_name):
    for file_name, file_info in repo.directory_contents(directory_path):
        if file_info.type == 'file' and file_name.endswith('.py'):
            print(f"Processing {file_name} in {repo_name}")
            file_content = await get_file_content(repo, file_info.path)
            updated_content = process_file(file_content, correct_urls, repo_name)
            if updated_content != file_content:
                await create_commit_and_pull_request(
                    repo, file_info.path, updated_content, repo_name
                )
        elif file_info.type == 'dir':
            await process_directory(repo, file_info.path, correct_urls, repo_name)


async def get_file_content(repo, file_path):
    file = repo.file_contents(file_path)
    return file.decoded.decode('utf-8')


def process_file(file_content, correct_urls, collection_name):
    block_names = extract_block_name_from_file_content(file_content)

    for block_name in block_names:
        slugified_block_name = slugify(block_name)
        print
        if slugified_block_name in correct_urls.get(collection_name, {}):
            pattern = (
                fr'(_block_type_name\s*=\s*"{re.escape(block_name)}"[^{{}}]*_logo_url = )"https?://images.ctfassets.net/[^"]+"'
            )

            match = re.search(pattern, file_content)
            if match:
                print(f"\t\tFound match for {block_name} in {collection_name}")
                new_url = correct_urls[collection_name][slugified_block_name]
                file_content = (
                    f"{file_content[:match.start(1)]}"
                    f"{match.group(1)}"
                    f'"{new_url}"'  # Ensure the URL is within quotes
                    f"{file_content[match.end(1):]}"
                )
    return file_content


def extract_block_name_from_file_content(file_content):
    BLOCK_TYPE_NAME_PATTERN = r"_block_type_name\s*=\s*\"([^\"]+)\""
    return [
        match.group(1) for match in re.finditer(BLOCK_TYPE_NAME_PATTERN, file_content)
    ]

def slugify(text):
    return text.lower().replace(" ", "-")

async def create_commit_and_pull_request(repo, file_path, updated_content, repo_name):
    branch_name = f"update-logo-urls-{repo_name}"
    await repo.create_branch_ref(branch_name, repo.branch("main").commit.sha)
    commit_message = f"Update logo URL in {file_path}"
    repo.create_file(file_path, commit_message, updated_content, branch=branch_name)
    repo.create_pull(
        title="Update Logo URLs",
        body="Automated update of logo URLs in block definitions.",
        base="main", head=branch_name
    )

async def main(repos: list[str]):
    await process_repos(repos, await get_correct_logo_urls())

if __name__ == "__main__":
    asyncio.run(main(["prefect-twitter"]))