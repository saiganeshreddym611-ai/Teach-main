from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tutor.content import clear_pack_cache, load_pack
from tutor.main import app
from tutor.retrieval.corpus import load_corpus
from tutor.retrieval.refs import UnresolvedRef, parse_ref, ref_label, resolve_ref
from scripts import validate_pack

FIXTURES = Path(__file__).parent / "fixtures" / "packs"


@pytest.fixture
def corpus():
    return load_corpus(load_pack("fixture_115", packs_dir=FIXTURES))


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("IndAS115.para.9-16", ("IndAS115", "9", "16", "")),
        ("IndAS115.para.22(b)", ("IndAS115", "22", None, "(b)")),
        ("IndAS115.para.B28-B33", ("IndAS115", "B28", "B33", "")),
        ("IndAS37.para.66-69", ("IndAS37", "66", "69", "")),
    ],
)
def test_parse_forms(ref, expected):
    parsed = parse_ref(ref)
    assert parsed is not None
    assert (parsed.doc_code, parsed.start, parsed.end, parsed.sub) == expected
    assert parse_ref("ICAI.SM.FR.ch1.s1.p1") is None


def test_every_real_ref_parses():
    pack = load_pack("ind_as_115")
    assert all(parse_ref(ref) is not None for node in pack.curriculum.tree.nodes for ref in node.source_refs)


def test_resolve_single_range_sub(corpus):
    assert [p.passage_id for p in resolve_ref("IndAS115.para.9-11", corpus)] == [
        "IndAS115.para.9", "IndAS115.para.10", "IndAS115.para.11"
    ]
    assert [p.passage_id for p in resolve_ref("IndAS115.para.22(b)", corpus)] == ["IndAS115.para.22"]
    assert len(resolve_ref("IndAS115.para.B28-B30", corpus)) == 3
    assert len(resolve_ref("IndAS37.para.66-69", corpus)) == 4


def test_range_uses_document_order(corpus):
    assert [p.passage_id for p in resolve_ref("IndAS115.para.11-27A", corpus)] == [
        "IndAS115.para.11", "IndAS115.para.22", "IndAS115.para.27A"
    ]


def test_resolve_exact_id(corpus):
    assert resolve_ref("ICAI.SM.FR.ch1.s1.p1", corpus)[0].passage_id == "ICAI.SM.FR.ch1.s1.p1"


@pytest.mark.parametrize("ref", ["IndAS115.para.999", "Unknown.para.9", "IndAS115.para.11-9", "nonsense"])
def test_unresolved(ref, corpus):
    with pytest.raises(UnresolvedRef) as exc:
        resolve_ref(ref, corpus)
    assert exc.value.reason


def test_labels(corpus):
    assert ref_label("IndAS115.para.9", corpus) == "Ind AS 115, para 9"
    assert ref_label("IndAS115.para.9-11", corpus) == "Ind AS 115, paras 9–11"
    assert ref_label("IndAS115.para.22(b)", corpus) == "Ind AS 115, para 22(b)"
    assert ref_label("ICAI.SM.FR.ch1.s1.p1", corpus) == "ICAI Study Material, Ch 1 §1"
    assert ref_label("RTP.2099-01.q1.ans", corpus) == "RTP January 2099, Q1 (answer)"


def test_passage_endpoint(monkeypatch):
    from tutor import config
    monkeypatch.setattr(config.settings, "content_pack", "fixture_115")
    monkeypatch.setattr("tutor.content.PACKS_DIR", FIXTURES)
    clear_pack_cache()
    with TestClient(app) as client:
        response = client.get("/passages/IndAS115.para.9")
        assert response.status_code == 200
        body = response.json()
        assert body["passage"]["passage_id"] == "IndAS115.para.9"
        assert body["source"]["doc_id"] == "fx_std115"
        assert body["citation"]["label"] == "Ind AS 115, para 9"
        assert client.get("/passages/nope").status_code == 404


def test_validator_passes_on_fixture():
    assert validate_pack.main(["--pack", "fixture_115", "--packs-dir", str(FIXTURES)]) == 0


def test_validator_fails_on_broken_ref(tmp_path):
    destination = tmp_path / "packs"
    shutil.copytree(FIXTURES, destination)
    concept = destination / "fixture_115" / "concept_map.json"
    data = json.loads(concept.read_text(encoding="utf-8"))
    data["nodes"][0]["source_refs"][0] = "IndAS115.para.999"
    concept.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    clear_pack_cache()
    assert validate_pack.main(["--pack", "fixture_115", "--packs-dir", str(destination)]) == 1


def test_validator_without_corpus(tmp_path):
    destination = tmp_path / "packs"
    shutil.copytree(FIXTURES, destination)
    shutil.rmtree(destination / "fixture_115" / "corpus")
    clear_pack_cache()
    assert validate_pack.main(["--pack", "fixture_115", "--packs-dir", str(destination)]) == 2


def test_real_pack_refs_resolve():
    real_pack = load_pack("ind_as_115")
    if load_corpus(real_pack) is None:
        pytest.skip("ind_as_115 has no corpus yet (H1)")
    assert validate_pack.main(["--pack", "ind_as_115"]) == 0
