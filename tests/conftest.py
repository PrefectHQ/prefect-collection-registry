import pytest
from prefect.testing.utilities import prefect_test_harness


@pytest.fixture(autouse=True)
def prefect_db():
    with prefect_test_harness():
        yield
