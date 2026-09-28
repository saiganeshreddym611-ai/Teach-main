from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tutor.content import ContentPackError, load_pack
from tutor.contracts.jobs import JobProfile, JobRequirement
from tutor.jobs import load_job_profiles, meets, missing_nodes, qualified
from tutor.models import NodeStatus
from tutor.node_selector import select_next_node


REPO_ROOT = Path(__file__).resolve().parents[3]
PACK_ROOT = REPO_ROOT / "content" / "packs" / "ind_as_115"


def _copy_pack(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "packs"
    shutil.copytree(PACK_ROOT, packs_dir / "ind_as_115")
    return packs_dir


def _profile(required: list[JobRequirement], adjacent: list[JobRequirement] | None = None) -> JobProfile:
    return JobProfile(
        job_id="test",
        title="Test",
        sector="Test",
        required=required,
        adjacent=adjacent or [],
    )


def test_seed_profile_loads():
    profile = load_job_profiles(load_pack("ind_as_115"))["revenue_accountant_seed"]
    node_ids = set(load_pack("ind_as_115").curriculum.by_id)
    assert all(requirement.node_id in node_ids for requirement in profile.required + profile.adjacent)


def test_unknown_node_rejected(tmp_path):
    packs_dir = _copy_pack(tmp_path)
    profile_path = packs_dir / "ind_as_115" / "job_profiles" / "bad.json"
    profile_path.write_text(
        json.dumps({"job_id": "bad", "title": "Bad", "sector": "Test", "required": [{"node_id": "bad"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ContentPackError, match="bad.json"):
        load_job_profiles(load_pack("ind_as_115", packs_dir=packs_dir))


def test_duplicate_job_id_rejected(tmp_path):
    packs_dir = _copy_pack(tmp_path)
    profile = json.loads(
        (packs_dir / "ind_as_115" / "job_profiles" / "revenue_accountant.json").read_text(encoding="utf-8")
    )
    (packs_dir / "ind_as_115" / "job_profiles" / "duplicate.json").write_text(
        json.dumps(profile), encoding="utf-8"
    )
    with pytest.raises(ContentPackError, match="duplicate"):
        load_job_profiles(load_pack("ind_as_115", packs_dir=packs_dir))


def test_meets_ranking():
    assert not meets(NodeStatus.GAP, "PARTIAL")
    assert meets(NodeStatus.PARTIAL, "PARTIAL")
    assert not meets(NodeStatus.PARTIAL, "VERIFIED")
    assert not meets(None, "PARTIAL")


def test_qualified_projection():
    profile = _profile([JobRequirement(node_id="a"), JobRequirement(node_id="b", min_status="PARTIAL")])
    assert not qualified(profile, {"a": NodeStatus.VERIFIED})
    assert qualified(profile, {"a": NodeStatus.VERIFIED, "b": NodeStatus.PARTIAL})
    assert qualified(profile, {"a": NodeStatus.VERIFIED, "b": NodeStatus.PARTIAL, "x": NodeStatus.GAP})


def test_missing_nodes_in_profile_order():
    profile = _profile(
        [JobRequirement(node_id="a"), JobRequirement(node_id="b"), JobRequirement(node_id="c", min_status="PARTIAL")]
    )
    assert missing_nodes(profile, {"b": NodeStatus.VERIFIED, "c": NodeStatus.GAP}) == ["a", "c"]


def test_selector_core_before_adjacent(curriculum):
    profile = _profile(
        [JobRequirement(node_id="ind_as_115.step_2"), JobRequirement(node_id="ind_as_115.step_1")],
        [JobRequirement(node_id="ind_as_115.step_1.criteria")],
    )
    assert select_next_node(curriculum, {}, [], job_profile=profile) == "ind_as_115.step_1"
    status = {"ind_as_115.step_1": NodeStatus.VERIFIED, "ind_as_115.step_2": NodeStatus.VERIFIED}
    assert select_next_node(curriculum, status, [], job_profile=profile) == "ind_as_115.step_1.criteria"


def test_selector_ignores_nodes_outside_profile(curriculum):
    profile = _profile([JobRequirement(node_id="ind_as_115.step_2")])
    assert select_next_node(curriculum, {}, [], job_profile=profile) == "ind_as_115.step_2"
    assert select_next_node(
        curriculum, {"ind_as_115.step_2": NodeStatus.VERIFIED}, [], job_profile=profile
    ) is None
