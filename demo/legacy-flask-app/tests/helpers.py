"""Framework-agnostic response helpers.

Works with both the Flask test client (resp.get_json()) and HTTP-style test
clients such as fastapi.testclient.TestClient (resp.json()).
"""


def body(resp):
    if hasattr(resp, "get_json"):
        return resp.get_json()
    return resp.json()
