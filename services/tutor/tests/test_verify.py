import base64

import pytest
from httpx import ASGITransport, AsyncClient

from tutor import main
from tutor.config import settings
from tutor.integrity import VERIFIERS, UnknownVerifierError, get_verifier


@pytest.fixture
def silence() -> bytes:
    return b"\x00" * 32_000


@pytest.mark.parametrize("name", sorted(VERIFIERS))
async def test_verifier_conformance(name: str, silence: bytes):
    verifier = VERIFIERS[name]()
    assert await verifier.enroll("student_1", silence) is None

    result1 = await verifier.verify("student_1", silence)
    result2 = await verifier.verify("student_1", silence)

    assert isinstance(result1.match, bool)
    assert isinstance(result2.match, bool)
    assert 0.0 <= result1.score <= 1.0
    assert 0.0 <= result2.score <= 1.0
    assert result1.method
    assert result2.method
    assert result1 == result2


async def test_verify_endpoint_ok(silence: bytes):
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/verify",
            json={"student_id": "student_1", "audio_b64": base64.b64encode(silence).decode()},
        )
    assert r.status_code == 200
    assert r.json() == {"match": True, "score": 1.0, "method": "stub"}


async def test_verify_bad_base64():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/verify",
            json={"student_id": "student_1", "audio_b64": "not base64!!"},
        )
    assert r.status_code == 422


async def test_verify_bad_student_id():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/verify",
            json={"student_id": "a b", "audio_b64": base64.b64encode(b"\x00\x00").decode()},
        )
    assert r.status_code == 422


def test_unknown_verifier(monkeypatch):
    monkeypatch.setattr(settings, "speaker_verifier", "nope")
    get_verifier.cache_clear()
    with pytest.raises(UnknownVerifierError, match="stub"):
        get_verifier()
    monkeypatch.setattr(settings, "speaker_verifier", "stub")
    get_verifier.cache_clear()


async def test_health_reports_verifier():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["verifier"] == "stub"
