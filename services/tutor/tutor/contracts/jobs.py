from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    min_status: Literal["PARTIAL", "VERIFIED"] = "VERIFIED"


class JobProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    title: str
    sector: str
    required: list[JobRequirement]
    adjacent: list[JobRequirement] = []
    pay_band: str = ""
