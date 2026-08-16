import pytest

from nyankoface_mcp.config import Settings, normalize_public_base_url


@pytest.mark.parametrize(
    "value",
    [
        "https://192.168.11.22:8443",
        "http://10.0.0.5:8443",
        "http://forgejo:3000",
        "http://mcp-admin:8001",
        "https://service.internal",
        "https://service.corp",
        "https://mcp.home.arpa",
        "https://mcp.localhost",
        "https://127.0.0.1:8443",
        "https://127.1:8443",
        "https://192.168.001.001:8443",
    ],
)
def test_public_base_url_rejects_private_or_internal_origins(value):
    with pytest.raises(ValueError, match="public origin"):
        normalize_public_base_url(value)


def test_public_base_url_accepts_public_origin_and_strips_trailing_slash():
    assert normalize_public_base_url("https://madesk.tail8be30.ts.net/") == (
        "https://madesk.tail8be30.ts.net"
    )


def test_localhost_remains_available_for_local_development():
    assert Settings(public_base_url="https://localhost:8443").public_base_url == (
        "https://localhost:8443"
    )


def test_test_domain_requires_an_explicit_fixture_override():
    with pytest.raises(ValueError, match="public origin"):
        Settings(public_base_url="https://ha.test")
    assert Settings(
        public_base_url="https://ha.test",
        allow_test_public_base_url=True,
    ).public_base_url == "https://ha.test"
    with pytest.raises(ValueError, match="public origin"):
        Settings(
            public_base_url="https://other.test",
            allow_test_public_base_url=True,
        )
