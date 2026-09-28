from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from .content import ContentPack, ContentPackError
from .contracts.jobs import JobProfile
from .models import NodeStatus


_STATUS_RANK = {
    NodeStatus.NOT_MENTIONED: 0,
    NodeStatus.GAP: 0,
    NodeStatus.PARTIAL: 1,
    NodeStatus.VERIFIED: 2,
}


def load_job_profiles(pack: ContentPack) -> dict[str, JobProfile]:
    directory = pack.root / "job_profiles"
    if not directory.is_dir():
        return {}

    profiles: dict[str, JobProfile] = {}
    node_ids = set(pack.curriculum.by_id)
    for path in sorted(directory.glob("*.json")):
        try:
            profile = JobProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise ContentPackError(f"{path}: {exc}") from exc

        requirements = profile.required + profile.adjacent
        requirement_ids = [requirement.node_id for requirement in requirements]
        invalid_nodes = sorted(set(requirement_ids) - node_ids)
        if invalid_nodes:
            raise ContentPackError(
                f"{path}: node IDs are not in the pack curriculum: {', '.join(invalid_nodes)}"
            )
        duplicates = sorted(
            {node_id for node_id in requirement_ids if requirement_ids.count(node_id) > 1}
        )
        if duplicates:
            raise ContentPackError(f"{path}: duplicate node IDs: {', '.join(duplicates)}")
        if profile.job_id in profiles:
            raise ContentPackError(f"{path}: duplicate job_id '{profile.job_id}'")
        profiles[profile.job_id] = profile
    return profiles


def meets(status: NodeStatus | None, min_status: str) -> bool:
    if status is None:
        return False
    return _STATUS_RANK[status] >= _STATUS_RANK[NodeStatus(min_status)]


def missing_nodes(profile: JobProfile, status: dict[str, NodeStatus]) -> list[str]:
    return [
        requirement.node_id
        for requirement in profile.required
        if not meets(status.get(requirement.node_id), requirement.min_status)
    ]


def qualified(profile: JobProfile, status: dict[str, NodeStatus]) -> bool:
    return not missing_nodes(profile, status)
