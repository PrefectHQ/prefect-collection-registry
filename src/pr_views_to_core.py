import os
import subprocess
from datetime import datetime
from prefect.blocks.system import Secret

GITHUB_TOKEN = Secret.load("collection-registry-contents-prs-rw-pat").get()
SOURCE_REPO_URL = 'https://raw.githubusercontent.com/PrefectHQ/prefect-collection-registry/main/views/aggregate-worker-metadata.json'
TARGET_FILE_PATH = 'src/prefect/server/api/collections_data/views/aggregate-worker-metadata.json' # noqa: E501
TARGET_ORG = 'PrefectHQ'
TARGET_REPO = 'prefect'
NEW_BRANCH = f'update-worker-metadata-{datetime.now().strftime("%Y%m%d%H%M%S")}'

commands = f"""
    git clone https://github.com/{TARGET_ORG}/{TARGET_REPO}.git &&
    cd {TARGET_REPO} &&
    mkdir -p {os.path.dirname(TARGET_FILE_PATH)} &&
    curl -o {TARGET_FILE_PATH} {SOURCE_REPO_URL} &&
    git config user.email "marvin@prefect.io" &&
    git config user.name "marvin-robot" &&
    git remote set-url origin https://x-access-token:{GITHUB_TOKEN}@github.com/{TARGET_ORG}/{TARGET_REPO}.git &&
    git checkout -b {NEW_BRANCH} &&
    git add {TARGET_FILE_PATH} &&
    git commit -m "Update aggregate-worker-metadata.json" &&
    git push --set-upstream origin {NEW_BRANCH} &&
    gh pr create --repo {TARGET_ORG}/{TARGET_REPO} --base main --head {NEW_BRANCH} --title "Automated PR for Worker Metadata Update" --body "This is an automated PR to update the worker metadata."
""" # noqa: E501
subprocess.check_call(commands, shell=True)
