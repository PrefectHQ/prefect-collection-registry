import os
import subprocess
import sys
import asyncio
import httpx
from datetime import datetime

from prefect.blocks.system import Secret

GITHUB_TOKEN = Secret.load("collection-registry-contents-prs-rw-pat").get()
os.environ['GITHUB_TOKEN'] = GITHUB_TOKEN

SOURCE_REPO_URL = 'https://raw.githubusercontent.com/PrefectHQ/prefect-collection-registry/main/views/aggregate-worker-metadata.json'
TARGET_FILE_PATH = 'src/prefect/server/api/collections_data/views/aggregate-worker-metadata.json' # noqa E501
TARGET_ORG = 'PrefectHQ'
TARGET_REPO = 'prefect'
NEW_BRANCH = f'update-worker-metadata-{datetime.now().strftime("%Y%m%d%H%M%S")}'

commands = f"""
    mkdir -p {os.path.dirname(TARGET_FILE_PATH)} &&
    curl -o {TARGET_FILE_PATH} {SOURCE_REPO_URL} &&
    gh auth login &&
    git checkout -b {NEW_BRANCH} &&
    git add {TARGET_FILE_PATH} &&
    git commit -m "Update aggregate-worker-metadata.json" &&
    gh pr create --base main --head {NEW_BRANCH} --title "Automated PR for Worker Metadata Update" --fill
""" # noqa E501
subprocess.check_call(commands, shell=True)

async def create_pull_request(new_branch: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f'https://api.github.com/repos/{TARGET_ORG}/{TARGET_REPO}/pulls',
            headers={'Authorization': f'token {GITHUB_TOKEN}'},
            json={
                'title': 'Automated PR for Worker Metadata Update',
                'head': new_branch,
                'base': 'main'
            }
        )
    
    if response.status_code == 201:
        print('Pull request created successfully.')
    else:
        print('Failed to create pull request:', response.json())

if __name__ == '__main__':
    new_branch = sys.argv[1] if len(sys.argv) > 1 else NEW_BRANCH
    asyncio.run(create_pull_request(new_branch))
