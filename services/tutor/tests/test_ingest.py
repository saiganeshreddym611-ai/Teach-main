from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from tutor.content import ContentPackError, load_pack, load_sources
from tutor.contracts.content import SourceDoc
from tutor.ingest import IngestError, SPLITTERS, build_corpus, write_corpus
from tutor.ingest.pipeline import SplitContext
from tutor.ingest.qa import split_qa
from tutor.ingest.standard import split_amendment, split_standard
from tutor.ingest.study_material import MAX_WORDS, split_study_material


TESTS_DIR = Path(__file__).resolve().parent
FIXTURE_ROOT = TESTS_DIR / "fixtures" / "packs" / "fixture_115"
FIXTURE_PACKS = FIXTURE_ROOT.parent
MARKER = "[TEST FIXTURE - NOT SYLLABUS TEXT]"


def source_doc(
    doc_type: str = "standard",
    *,
    doc_id: str = "fixture-doc",
    doc_code: str = "IndAS115",
    attempt: str | None = None,
) -> SourceDoc:
    return SourceDoc(
        doc_id=doc_id,
        doc_code=doc_code,
        title="Fixture document",
        short_name="Fixture",
        doc_type=doc_type,
        authority_rank=1,
        attempt=attempt,
        version="0.0.1",
        path="source.txt",
    )


def context(warnings: list[str] | None = None) -> SplitContext:
    return SplitContext("TEST PAPER", "2099-01", warnings if warnings is not None else [])


def test_standard_paragraph_numbers():
    text = "\n\n".join(
        f"{number} {MARKER} invented widget text."
        for number in ("9", "27A", "B28", "IE3", "C1")
    )
    passages = split_standard(source_doc(), text, context())
    assert [passage.locator for passage in passages] == [
        "para.9",
        "para.27A",
        "para.B28",
        "para.IE3",
        "para.C1",
    ]
    assert all(passage.text.startswith(passage.locator.removeprefix("para.") + " ") for passage in passages)


def test_standard_sub_items_stay_inside():
    text = (
        f"22 {MARKER} imaginary parent widget.\n\n"
        f"(a) {MARKER} imaginary first widget.\n\n"
        f"(b) {MARKER} imaginary second widget."
    )
    passages = split_standard(source_doc(), text, context())
    assert len(passages) == 1
    assert "(a)" in passages[0].text and "(b)" in passages[0].text


def test_wrapped_number_line_does_not_split():
    text = f"9 {MARKER} Fixture Co makes a widget.\n10 per cent of its paint is imaginary."
    passages = split_standard(source_doc(), text, context())
    assert len(passages) == 1
    assert "10 per cent" in passages[0].text


def test_heading_sets_section_and_preamble_skipped():
    warnings: list[str] = []
    text = (
        f"{MARKER} invented preamble.\n\n## Scope\n\n"
        f"9 {MARKER} a pretend widget paragraph."
    )
    passages = split_standard(source_doc(), text, context(warnings))
    assert len(passages) == 1
    assert passages[0].section == "Scope"
    assert len(warnings) == 1


def test_page_numbers():
    paged = f"9 {MARKER} first page.\n\f\n10 {MARKER} second page."
    plain = f"9 {MARKER} no page markers."
    assert split_standard(source_doc(), paged, context())[1].page == 2
    assert split_standard(source_doc(), plain, context())[0].page is None


def test_amendment_supersedes():
    text = (
        f"9 {MARKER} replacement widget description.\n"
        "Supersedes: IndAS115.para.7, IndAS115.para.8"
    )
    passage = split_amendment(source_doc("amendment"), text, context())[0]
    assert "Supersedes:" not in passage.text
    assert passage.supersedes == ["IndAS115.para.7", "IndAS115.para.8"]


def test_study_material_chunks():
    warnings: list[str] = []
    long_block = f"{MARKER} " + "imaginary widget " * 145
    oversized_block = f"{MARKER} " + "fictional widget " * 180
    text = (
        "Front matter.\n\n# Chapter 4 — Fixture\n\n## First\n\n"
        f"{long_block}\n\n{long_block}\n\n## Second\n\n"
        f"{oversized_block}\n\n# Chapter 5 — Fixture\n\n## Third\n\n"
        f"{MARKER} end."
    )
    passages = split_study_material(source_doc("study_material"), text, context(warnings))
    locators = [passage.locator for passage in passages]
    assert locators[:2] == ["ch4.s1.p1", "ch4.s1.p2"]
    assert "ch4.s2.p1" in locators and "ch5.s1.p1" in locators
    assert all(
        len(passage.text.split()) <= MAX_WORDS
        or (passage.locator == "ch4.s2.p1" and len(passage.text.split()) > MAX_WORDS)
        for passage in passages
    )
    assert any("exceed 350 words" in warning for warning in warnings)


def test_qa_splitter():
    text = (
        f"Question 1 {MARKER} describe an imaginary widget.\n\n"
        f"Answer 1 {MARKER} it is a fictional token.\n\n"
        f"Question 2 {MARKER} describe a pretend box.\n\n"
        "A company sells no real products.\n\n"
        f"Answer {MARKER} the box is imaginary."
    )
    passages = split_qa(source_doc("rtp"), text, context())
    assert [passage.locator for passage in passages] == ["q1", "q1.ans", "q2", "q2.ans"]
    assert "A company sells" in passages[2].text


def test_answer_before_question_errors():
    with pytest.raises(IngestError):
        split_qa(source_doc("rtp"), f"Answer {MARKER} imaginary answer.", context())


def _copy_fixture(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "packs"
    packs_dir.mkdir(parents=True)
    shutil.copytree(FIXTURE_ROOT, packs_dir / "fixture_115")
    return packs_dir


def test_duplicate_passage_ids_error(tmp_path):
    packs_dir = _copy_fixture(tmp_path)
    raw_path = packs_dir / "fixture_115" / "sources" / "raw" / "ind_as_115.txt"
    with raw_path.open("a", encoding="utf-8", newline="\n") as source:
        source.write(f"\n9 {MARKER} duplicate imaginary paragraph.\n")
    sources_path = packs_dir / "fixture_115" / "sources" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources[0]["sha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match="IndAS115.para.9"):
        build_corpus(load_pack("fixture_115", packs_dir=packs_dir))


def test_sha_mismatch_errors(tmp_path):
    packs_dir = _copy_fixture(tmp_path)
    sources_path = packs_dir / "fixture_115" / "sources" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources[0]["sha256"] = "0" * 64
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pack = load_pack("fixture_115", packs_dir=packs_dir)
    with pytest.raises(IngestError, match="update sources.json"):
        build_corpus(pack)
    assert build_corpus(pack, check_hashes=False)[1].built_from["fx_std115"] != "0" * 64


def test_unknown_extension_errors(tmp_path):
    packs_dir = _copy_fixture(tmp_path)
    pack_root = packs_dir / "fixture_115"
    raw_path = pack_root / "sources" / "raw" / "ind_as_115.txt"
    unsupported_path = raw_path.with_suffix(".docx")
    shutil.copyfile(raw_path, unsupported_path)
    sources_path = pack_root / "sources" / "sources.json"
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    sources[0]["path"] = "sources/raw/ind_as_115.docx"
    sources[0]["sha256"] = hashlib.sha256(unsupported_path.read_bytes()).hexdigest()
    sources_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(IngestError, match=".docx"):
        build_corpus(load_pack("fixture_115", packs_dir=packs_dir))


def test_ingest_is_deterministic(tmp_path):
    outputs = []
    for run in range(2):
        packs_dir = _copy_fixture(tmp_path / f"run-{run}")
        pack = load_pack("fixture_115", packs_dir=packs_dir)
        passages, manifest, _ = build_corpus(pack)
        write_corpus(pack, passages, manifest)
        outputs.append(
            (
                (pack.corpus_dir / "chunks.jsonl").read_bytes(),
                (pack.corpus_dir / "manifest.json").read_bytes(),
            )
        )
    assert outputs[0] == outputs[1]


def test_fixture_corpus_up_to_date():
    pack = load_pack("fixture_115", packs_dir=FIXTURE_PACKS)
    _, manifest, _ = build_corpus(pack)
    committed = json.loads((pack.corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest.corpus_sha256 == committed["corpus_sha256"]


def test_fixture_marker_everywhere():
    chunks_path = FIXTURE_ROOT / "corpus" / "chunks.jsonl"
    passages = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    assert passages
    assert all(MARKER in passage["text"] for passage in passages)


def test_passage_ids_unique_and_prefixed():
    pack = load_pack("fixture_115", packs_dir=FIXTURE_PACKS)
    passages, _, _ = build_corpus(pack)
    doc_codes = {doc.doc_id: doc.doc_code for doc in load_sources(pack)}
    ids = [passage.passage_id for passage in passages]
    assert len(ids) == len(set(ids))
    assert all(passage.passage_id.startswith(doc_codes[passage.doc_id] + ".") for passage in passages)


def test_load_sources_missing_and_duplicate_errors(tmp_path):
    pack = load_pack("fixture_115", packs_dir=FIXTURE_PACKS)
    assert load_sources(pack)
    temporary_root = tmp_path / "pack"
    shutil.copytree(FIXTURE_ROOT, temporary_root)
    (temporary_root / "sources" / "sources.json").unlink()
    missing_pack = replace(pack, root=temporary_root)
    assert load_sources(missing_pack) == []
    sources_path = temporary_root / "sources" / "sources.json"
    sources = json.loads((FIXTURE_ROOT / "sources" / "sources.json").read_text(encoding="utf-8"))
    sources.append(sources[0])
    sources_path.write_text(json.dumps(sources) + "\n", encoding="utf-8")
    with pytest.raises(ContentPackError, match="fx_std115"):
        load_sources(missing_pack)
    sources_path.write_text("{", encoding="utf-8")
    with pytest.raises(ContentPackError, match="sources.json"):
        load_sources(missing_pack)


def test_every_doc_type_has_splitter():
    assert set(SPLITTERS) == {"standard", "study_material", "rtp", "mtp", "past_paper", "amendment"}
