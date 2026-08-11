import pytest

from app import create_app


@pytest.fixture()
def client():
    app = create_app()
    with app.test_client() as test_client:
        yield test_client
