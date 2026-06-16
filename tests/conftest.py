# Importing prefect_github here forces it into sys.modules before the
# ephemeral Prefect server in prefect_test_harness starts. Without this,
# the server's block auto-registration walks prefect_github's
# GitHubCredentials (registered via the prefect.collections entry point)
# and crashes in Block._get_current_package_version when
# sys.modules["prefect_github"] is missing.
import prefect_github  # noqa: F401
import pytest
from prefect.testing.utilities import prefect_test_harness


@pytest.fixture(autouse=True)
def prefect_db():
    with prefect_test_harness():
        yield
