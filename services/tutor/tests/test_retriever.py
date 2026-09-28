from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from tutor.content import load_pack
from tutor.ingest.pipeline import build_corpus, write_corpus
from tutor.retrieval import Normaliser, PackRetriever, SearchFilters, get_retriever
from tutor.retrieval.corpus import Corpus
from scripts.calibrate_retrieval import calibrate

FIXTURES = Path(__file__).parent / "fixtures" / "packs"


@pytest.fixture
def retriever():
    return get_retriever(load_pack("fixture_115", packs_dir=FIXTURES))


def test_tokens():
    assert Normaliser({}).tokens("What is para B28 of the Standard?") == ["para", "b28", "standard"]


def test_synonyms_both_sides(retriever):
    assert retriever.normaliser.tokens("wup") == retriever.normaliser.tokens("widget unit price")
    assert retriever.search("wup")[0].passage.passage_id == "IndAS115.para.10"
    assert retriever.search("unit price of a widget")[0].passage.passage_id == "IndAS115.para.10"


def test_for_node_order_and_dedupe(retriever):
    assert [p.passage_id for p in retriever.for_node("fixture_115.one")] == [
        "IndAS115.para.9", "IndAS115.para.10", "IndAS115.para.11", "IndAS115.para.22"
    ]


def test_for_node_unknown(retriever):
    with pytest.raises(KeyError):
        retriever.for_node("missing")


def test_search_deterministic(retriever):
    assert retriever.search("widget token") == retriever.search("widget token")


def test_ties_broken_by_id():
    pack = load_pack("fixture_115", packs_dir=FIXTURES)
    corpus = get_retriever(pack).corpus
    passages = [
        corpus.passage("IndAS115.para.9").model_copy(update={"passage_id": "z", "text": "same"}),
        corpus.passage("IndAS115.para.10").model_copy(update={"passage_id": "a", "text": "same"}),
    ]
    tiny = Corpus(pack, passages, list(corpus.docs.values()), "tiny")
    result = PackRetriever(tiny, Normaliser({})).search("same")
    assert [item.passage.passage_id for item in result] == ["a", "z"]


def test_filters(retriever):
    doc_type_results = retriever.search("widget", filters=SearchFilters(doc_types=frozenset({"rtp"})))
    attempt_results = retriever.search("widget", filters=SearchFilters(attempt="2099-01"))
    chapter_results = retriever.search(
        "widget",
        filters=SearchFilters(chapter="Chapter 1 — Fixture Co widget notes"),
    )
    node_results = retriever.search(
        "widget",
        filters=SearchFilters(node_ids=frozenset({"fixture_115.one"})),
    )
    assert doc_type_results and all(item.passage.doc_type == "rtp" for item in doc_type_results)
    assert attempt_results and all(item.passage.attempt == "2099-01" for item in attempt_results)
    assert chapter_results and all(
        item.passage.chapter == "Chapter 1 — Fixture Co widget notes" for item in chapter_results
    )
    assert node_results and all(
        item.passage.passage_id
        in {"IndAS115.para.9", "IndAS115.para.10", "IndAS115.para.11", "IndAS115.para.22"}
        for item in node_results
    )


def test_confidence_range_and_extremes(retriever):
    assert all(0.0 <= item.confidence <= 1.0 for item in retriever.search("widget"))
    assert retriever.search("leases gst") == []
    assert retriever.search("purple widget label")[0].confidence == 1.0


def _fixture_queries():
    """The calibration file holds several packs; these tests use the fixture pack's questions."""
    lines = (Path(__file__).parent / "evals" / "retrieval" / "queries.jsonl").read_text(encoding="utf-8").splitlines()
    return [q for q in map(json.loads, lines) if q.get("pack") == "fixture_115"]


def test_recall_at_5(retriever):
    queries = _fixture_queries()
    assert calibrate(retriever, queries, 5)["recall_at_k"] >= 0.8


def test_out_of_syllabus_below_threshold(retriever):
    queries = _fixture_queries()
    result = calibrate(retriever, queries, 5)
    assert all(row["confidence"] < result["threshold"] for row in result["queries"] if not row["in_syllabus"])
    assert all(row["confidence"] >= result["threshold"] for row in result["queries"] if row["in_syllabus"])


def test_retriever_cache(tmp_path):
    destination = tmp_path / "packs"
    shutil.copytree(FIXTURES, destination)
    first = get_retriever(load_pack("fixture_115", packs_dir=destination))
    second = get_retriever(load_pack("fixture_115", packs_dir=destination))
    assert first is second
    pack_root = destination / "fixture_115"
    source_path = pack_root / "sources" / "raw" / "ind_as_115.txt"
    source_path.write_text(
        source_path.read_text(encoding="utf-8")
        + "\n\n999 [TEST FIXTURE - NOT SYLLABUS TEXT] Extra imaginary widget passage.\n",
        encoding="utf-8",
        newline="\n",
    )
    sources_path = pack_root / "sources" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources[0]["sha256"] = hashlib.sha256(source_path.read_bytes()).hexdigest()
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rebuilt_pack = load_pack("fixture_115", packs_dir=destination)
    passages, manifest, _ = build_corpus(rebuilt_pack)
    write_corpus(rebuilt_pack, passages, manifest)
    assert get_retriever(rebuilt_pack) is not first
    assert "IndAS115.para.999" in get_retriever(rebuilt_pack).corpus.by_id


def test_no_corpus(tmp_path):
    destination = tmp_path / "packs"
    shutil.copytree(FIXTURES, destination)
    shutil.rmtree(destination / "fixture_115" / "corpus")
    assert get_retriever(load_pack("fixture_115", packs_dir=destination)) is None


def test_grading_path_has_no_search(retriever, monkeypatch):
    monkeypatch.setattr(retriever, "search", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("search called")))
    assert retriever.for_node("fixture_115.one")
