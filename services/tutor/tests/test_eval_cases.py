"""Offline schema and helper checks for grader eval cases."""
from __future__ import annotations

import json
from pathlib import Path

from tutor.content import load_pack
from tutor.contracts.grading import GraderOutput, NodeVerdictV2
from tutor.models import NodeStatus
from tests.evals.grader.run_evals import (
    check_citations,
    check_omissions,
    counts_toward_failures,
)

CASES_DIR = Path(__file__).parent / "evals" / "grader" / "cases"
VALID_STATUSES = {status.value for status in NodeStatus}
VALID_STATUSES.add("!VERIFIED")


def test_every_case_is_valid():
    for path in sorted(CASES_DIR.glob("*.json")):
        case = json.loads(path.read_text(encoding="utf-8"))
        pack = load_pack(case.get("pack", "ind_as_115"))
        assert case.get("status", "reviewed") in {"draft", "reviewed"}
        assert isinstance(case["transcript"], str) and case["transcript"]
        assert case["expect"]
        assert all(node_id in pack.curriculum.by_id for node_id in case["expect"])
        assert all(expectation in VALID_STATUSES for expectation in case["expect"].values())

        corpus_path = pack.corpus_dir / "chunks.jsonl"
        passage_ids = set()
        if corpus_path.is_file():
            passage_ids = {
                json.loads(line)["passage_id"]
                for line in corpus_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
        for node_id, prefixes in case.get("expect_citations", {}).items():
            assert node_id in pack.curriculum.by_id
            assert prefixes
            assert all(
                any(passage_id.startswith(prefix) for passage_id in passage_ids)
                for prefix in prefixes
            )

        level_one_ids = {
            node.id for node in pack.curriculum.tree.nodes if node.level == 1
        }
        assert set(case.get("expect_omissions", [])) <= level_one_ids


def _output(node_id: str, passage_ids: list[str]) -> GraderOutput:
    return GraderOutput(
        verdicts=[
            NodeVerdictV2(
                node_id=node_id,
                status=NodeStatus.VERIFIED,
                confidence=0.9,
                passage_ids=passage_ids,
            )
        ],
        summary="scripted",
    )


def test_check_citations():
    node_id = "ind_as_37.recognition"
    assert check_citations(
        {node_id: ["IndAS37.para.14"]},
        [_output(node_id, ["IndAS37.para.14"])],
    ) == []
    assert check_citations(
        {node_id: ["IndAS37.para.99"]},
        [_output(node_id, ["IndAS37.para.14"])],
    )
    assert check_citations(
        {node_id: ["IndAS37.para.14"]},
        [
            _output(node_id, ["IndAS37.para.14"]),
            _output(node_id, ["IndAS37.para.14"]),
            _output(node_id, ["IndAS37.para.13"]),
        ],
    )


def test_check_omissions():
    curriculum = load_pack("ind_as_115").curriculum
    present = [
        node.id
        for node in curriculum.tree.nodes
        if node.level == 1 and node.id != "ind_as_115.step_4"
    ]
    output = GraderOutput(
        verdicts=[
            NodeVerdictV2(
                node_id=node_id,
                status=NodeStatus.VERIFIED,
                confidence=0.9,
            )
            for node_id in present
        ],
        summary="scripted",
    )
    assert check_omissions(["ind_as_115.step_4"], curriculum, [output]) == []


def test_drafts_do_not_count():
    assert counts_toward_failures("draft", include_drafts=False) is False
    assert counts_toward_failures("draft", include_drafts=True) is True
    assert counts_toward_failures("reviewed", include_drafts=False) is True
