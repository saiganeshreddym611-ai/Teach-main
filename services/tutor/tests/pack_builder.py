from __future__ import annotations

import json
from pathlib import Path


PREFIX = "[TEST FIXTURE - NOT SYLLABUS TEXT]"


def write_pack(root: Path, pack_id: str = "fx", n_nodes: int = 3, topic_id: str = "fx_topic") -> Path:
    pack = root / pack_id
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(
        json.dumps(
            {
                "pack_id": pack_id,
                "exam": PREFIX,
                "paper": PREFIX,
                "attempt": "2027-05",
                "version": "0.1.0",
                "topics": [topic_id],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    nodes = [
        {
            "id": f"{topic_id}.n{i}",
            "level": 1,
            "parent": None,
            "title": f"{PREFIX} Node {i}",
            "rubric": [f"{PREFIX} Rubric {i}"],
            "misconceptions": [f"{PREFIX} Misconception {i}"],
            "canonical_explanation": f"{PREFIX} Explanation {i}",
            "example": f"{PREFIX} Example {i}",
            "source_refs": [f"{PREFIX} Source {i}"],
        }
        for i in range(n_nodes)
    ]
    (pack / "concept_map.json").write_text(
        json.dumps(
            {
                "topic_id": topic_id,
                "subject": PREFIX,
                "standard": PREFIX,
                "opening_prompt": PREFIX,
                "nodes": nodes,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return pack
