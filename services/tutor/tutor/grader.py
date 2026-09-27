"""Grader: student transcript + rubric + linked source passages -> claims and cited verdicts.

Three implementations behind one interface, all returning `GraderOutput`:
- ClaudeGrader   : claude-opus-5, structured output, effort=high.
- OllamaGrader   : any Ollama model (default gemma4:31b-cloud), JSON-schema output.
- MockGrader     : deterministic keyword overlap, for key-less UI/dev runs.
- MemoGrader     : wraps any grader with in-memory memoisation and capture.

Code, not the model, has the last word: `_finalise()` removes anything the model may not cite or
reference and counts every correction for the audit log.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Protocol

from anthropic import AsyncAnthropic
from ollama import AsyncClient as OllamaAsyncClient
from ollama import ResponseError as OllamaResponseError

from .config import settings
from .contracts.grading import Claim, ClaimJudgment, GraderOutput, NodeVerdictV2, Omission
from .curriculum import Curriculum
from .grading_links import NodeLinks, node_links, passages_block, offered_passage_ids
from .grader_audit import (
    new_call_id,
    sha256_text,
    memo_key,
    grade_memo,
    write_capture,
)
from .models import NodeStatus
from .prompts import tree_block
from . import prompts

GRADED = {NodeStatus.VERIFIED, NodeStatus.PARTIAL, NodeStatus.GAP}


def _kept(values: list, allowed) -> list:
    """Values in `allowed`, first occurrence only, in the model's order."""
    return [v for v in dict.fromkeys(values) if v in allowed]


def _finalise(curriculum: Curriculum, output: GraderOutput, links: NodeLinks) -> tuple[GraderOutput, dict[str, int]]:
    """Make the model's output safe to record. Returns the cleaned output and a count per correction:
    unknown_node, unknown_claim_node, dropped_passage, node_link_added, dropped_rubric_index,
    dropped_misconception_index."""
    fixes: Counter[str] = Counter()
    verdicts: list[NodeVerdictV2] = []
    for v in output.verdicts:
        node = curriculum.by_id.get(v.node_id)
        if node is None:
            fixes["unknown_node"] += 1
            continue
        linked = links.ids(node.id)
        passage_ids = _kept(v.passage_ids, set(linked))
        fixes["dropped_passage"] += len(v.passage_ids) - len(passage_ids)
        origin = "model"
        if not passage_ids:
            origin = "node_link"
            if v.status in GRADED and linked:
                passage_ids = [linked[0]]
                fixes["node_link_added"] += 1
        rubric = _kept(v.rubric_items_met, range(len(node.rubric)))
        fixes["dropped_rubric_index"] += len(v.rubric_items_met) - len(rubric)
        misconceptions = _kept(v.misconception_ids, range(len(node.misconceptions)))
        fixes["dropped_misconception_index"] += len(v.misconception_ids) - len(misconceptions)
        verdicts.append(v.model_copy(update={
            "passage_ids": passage_ids, "citation_origin": origin,
            "rubric_items_met": rubric, "misconception_ids": misconceptions,
        }))

    claims: list[Claim] = []
    every_linked = links.all_ids()
    for i, c in enumerate(output.claims, start=1):
        node_id = c.node_id if c.node_id in curriculum.by_id else None
        if c.node_id and node_id is None:
            fixes["unknown_claim_node"] += 1
        allowed = set(links.ids(node_id)) if node_id else every_linked
        passage_ids = _kept(c.passage_ids, allowed)
        fixes["dropped_passage"] += len(c.passage_ids) - len(passage_ids)
        claims.append(c.model_copy(update={"claim_id": f"c{i}", "node_id": node_id, "passage_ids": passage_ids}))

    cleaned = GraderOutput(claims=claims, verdicts=verdicts, summary=output.summary)
    return cleaned, {k: n for k, n in sorted(fixes.items()) if n}


def omissions(curriculum: Curriculum, output: GraderOutput, links: NodeLinks) -> list[Omission]:
    """Level-1 nodes with no graded evidence anywhere in their subtree, in tree order, each with
    its node's citations. Computed by code after a diagnostic."""
    evidenced = {v.node_id for v in output.verdicts if v.status in GRADED}
    return [
        Omission(node_id=n.id, citations=links.citations(n.id))
        for n in curriculum.tree.nodes
        if n.level == 1 and not evidenced.intersection(curriculum.subtree_ids(n.id))
    ]


def _user_content(curriculum: Curriculum, transcript: str, focus_node_id: str | None, prior_context: str) -> str:
    if focus_node_id:
        node = curriculum.node(focus_node_id)
        focus = (
            "<focus>\nThis is a TEACH-BACK. The student was asked to explain the node "
            f"`{node.id}` (\"{node.title}\") in their own words.\n"
            f"You MUST return a verdict for `{node.id}`. Also return verdicts for any other nodes "
            "the student's words give evidence for.\n</focus>\n"
        )
    else:
        focus = (
            "<focus>\nThis is the BASELINE DIAGNOSTIC. The student was asked to say everything they know "
            "about the topic. Return verdicts for every node their words give evidence for (VERIFIED, PARTIAL or GAP).\n</focus>\n"
        )
    prior = f"<prior_context>\n{prior_context}\n</prior_context>\n" if prior_context else ""
    return f"{focus}{prior}<student_transcript>\n{transcript}\n</student_transcript>"


class Grader(Protocol):
    async def grade(
        self,
        curriculum: Curriculum,
        transcript: str,
        *,
        focus_node_id: str | None,
        prior_context: str,
        session_id: str,
        student_id: str = "",
        call_id: str | None = None,
    ) -> GraderOutput: ...


def _system_blocks(curriculum: Curriculum, links: NodeLinks, focus_node_id: str | None) -> list[dict]:
    blocks = [tree_block(curriculum)]
    passages = passages_block(curriculum, links, focus_node_id)
    if passages:
        blocks.append(passages)
    blocks.append({"type": "text", "text": prompts.GRADER_INSTRUCTIONS})
    return blocks


def _system_text(curriculum: Curriculum, links: NodeLinks, focus_node_id: str | None) -> str:
    blocks = _system_blocks(curriculum, links, focus_node_id)
    return "\n\n".join(b["text"] for b in blocks)


class ClaudeGrader:
    def __init__(self, client: AsyncAnthropic | None = None):
        self.client = client or AsyncAnthropic()

    async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None) -> GraderOutput:
        links = node_links(curriculum)
        user = _user_content(curriculum, transcript, focus_node_id, prior_context)
        call_id = call_id or new_call_id()
        start = time.perf_counter()
        response = await self.client.messages.parse(
            model=settings.model,
            max_tokens=16000,
            system=_system_blocks(curriculum, links, focus_node_id),
            messages=[{"role": "user", "content": user}],
            output_format=GraderOutput,
            output_config={"effort": "high"},
        )
        latency_ms = round((time.perf_counter() - start) * 1000)
        if response.stop_reason == "refusal":
            raise RuntimeError(f"grader refused: {response.stop_details}")
        raw: GraderOutput | None = response.parsed_output
        if raw is None:
            raise RuntimeError(f"grader returned no parsed output (stop_reason={response.stop_reason})")
        result, fixes = _finalise(curriculum, raw, links)
        _capture(
            session_id=session_id,
            student_id=student_id,
            focus_node_id=focus_node_id,
            call_id=call_id,
            curriculum=curriculum,
            links=links,
            user=user,
            result=result,
            fixes=fixes,
            provider="claude",
            model=response.model,
            request_id=getattr(response, "_request_id", None),
            usage=response.usage.model_dump() if response.usage else None,
            latency_ms=latency_ms,
            phase="teach_back" if focus_node_id else "diagnostic",
        )
        return result


def _inline_schema(schema: dict) -> dict:
    """Resolve local $refs and forbid extra keys. Ollama cannot grammar-constrain
    cloud models, so the schema is advisory there - a flat, explicit one is
    followed far more reliably than one full of $defs."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            out = {k: walk(v) for k, v in node.items() if k != "$defs"}
            if out.get("type") == "object" and "properties" in out:
                out.setdefault("additionalProperties", False)
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)


def _extract_json(text: str) -> str:
    """Tolerate the two most common wrappers models add around JSON: markdown
    code fences and prose before/after the object. Anything else still fails
    validation and triggers the corrective retry."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
        t = t.strip()
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
    # Take the first complete JSON object; ignore prose before it and anything
    # after it (some models keep talking, or emit the object twice).
    a = t.find("{")
    if a != -1:
        try:
            _, end = json.JSONDecoder().raw_decode(t, a)
            return t[a:end]
        except ValueError:
            pass
    return t


OLLAMA_OUTPUT_CONTRACT = """
Output format - return ONLY a JSON object of exactly this shape, nothing else:
{"claims": [{"claim_id": "c1", "quote": "<the student's words, <= 25 words>", "node_id": "<id from the tree, or null>", "judgment": "ACCURATE|INACCURATE|MISCONCEPTION|UNSUPPORTED|OFF_SYLLABUS", "passage_ids": []}],
 "verdicts": [{"node_id": "<id from the tree>", "status": "VERIFIED|PARTIAL|GAP|NOT_MENTIONED", "confidence": 0.0-1.0, "evidence": "<= 25 words", "rubric_items_met": [0], "misconception_ids": [], "passage_ids": []}],
 "summary": "<one sentence>"}
- "claims" and "verdicts" are lists, never objects keyed by id.
- "status" is exactly one of VERIFIED, PARTIAL, GAP, NOT_MENTIONED.
- rubric_items_met and misconception_ids are 0-based positions in that node's lists.
- passage_ids are ids of <passage> elements above; use [] when there are none.
- Do not add keys that are not in the shape above.
"""


class OllamaGrader:
    """Same prompts as ClaudeGrader, sent to an Ollama model with the GraderOutput
    JSON schema as `format` plus an explicit shape contract. temperature=0 for
    repeatable verdicts. One corrective retry if the shape is wrong."""

    def __init__(self, client: OllamaAsyncClient | None = None, model: str | None = None):
        self.client = client or OllamaAsyncClient(host=settings.ollama_host)
        self.model = model or settings.ollama_grader_model
        self.schema = _inline_schema(GraderOutput.model_json_schema())

    async def _chat(self, messages: list[dict]):
        kw = {} if settings.ollama_grader_think is None else {"think": settings.ollama_grader_think}
        for attempt in (1, 2):
            try:
                return await self.client.chat(
                    model=self.model,
                    messages=messages,
                    format=self.schema,
                    options={"temperature": 0, "num_ctx": 32768},
                    **kw,
                )
            except OllamaResponseError as e:
                # :cloud models occasionally 502 on a TLS/proxy hiccup; one retry clears it.
                if attempt == 2 or (e.status_code or 500) < 500:
                    raise
            except (ConnectionError, TimeoutError):
                if attempt == 2:
                    raise

    async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None) -> GraderOutput:
        links = node_links(curriculum)
        user = _user_content(curriculum, transcript, focus_node_id, prior_context)
        blocks = _system_blocks(curriculum, links, focus_node_id)
        system = "\n\n".join(b["text"] for b in blocks) + OLLAMA_OUTPUT_CONTRACT
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        call_id = call_id or new_call_id()
        start = time.perf_counter()
        response = await self._chat(messages)
        latency_ms = round((time.perf_counter() - start) * 1000)
        content = response.message.content or ""
        try:
            raw = GraderOutput.model_validate_json(_extract_json(content))
        except Exception as first_err:
            # One corrective round-trip: show the model its own output and the error.
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": (
                    f"That output does not match the required shape ({type(first_err).__name__}). "
                    "Re-emit the same claims and verdicts as a JSON object with top-level \"claims\" and "
                    "\"verdicts\" LISTS and a \"summary\" string, exactly as specified in the output format. JSON only."
                )},
            ]
            response = await self._chat(messages)
            content = response.message.content or ""
            try:
                raw = GraderOutput.model_validate_json(_extract_json(content))
            except Exception as e:
                raise RuntimeError(f"ollama grader returned invalid JSON twice ({e}): {content[:300]}") from e
        result, fixes = _finalise(curriculum, raw, links)
        _capture(
            session_id=session_id,
            student_id=student_id,
            focus_node_id=focus_node_id,
            call_id=call_id,
            curriculum=curriculum,
            links=links,
            user=user,
            result=result,
            fixes=fixes,
            provider="ollama",
            model=response.model,
            request_id=None,
            usage={"prompt_eval_count": response.prompt_eval_count, "eval_count": response.eval_count,
                   "total_ms": round((response.total_duration or 0) / 1e6), "retried": len(messages) > 2},
            latency_ms=latency_ms,
            phase="teach_back" if focus_node_id else "diagnostic",
        )
        return result


def _capture(
    *,
    session_id: str,
    student_id: str,
    focus_node_id: str | None,
    call_id: str,
    curriculum: Curriculum,
    links: NodeLinks,
    user: str,
    result: GraderOutput,
    fixes: dict[str, int],
    provider: str,
    model: str,
    request_id: str | None,
    usage: dict | None,
    latency_ms: int,
    phase: str,
    memo_hit: bool = False,
    memo_of: str | None = None,
) -> None:
    """Every grader call is an eval candidate. Write it to disk."""
    if not settings.capture_grader_calls:
        return
    try:
        settings.grader_capture_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        system_text = _system_text(curriculum, links, focus_node_id)
        payload = {
            "grader_call_id": call_id,
            "ts": ts,
            "session_id": session_id,
            "student_id": student_id,
            "phase": phase,
            "focus_node_id": focus_node_id,
            "focus_rubric": curriculum.node(focus_node_id).rubric if focus_node_id and focus_node_id in curriculum.by_id else [],
            "provider": provider,
            "model": model,
            "request_id": request_id,
            "prompt_version": prompts.PROMPT_VERSION,
            "content_hash": getattr(curriculum, "content_hash", None),
            "system_sha256": sha256_text(system_text),
            "offered_passage_ids": offered_passage_ids(curriculum, links, focus_node_id),
            "input": user,
            "output": result.model_dump(mode="json"),
            "corrections": fixes,
            "latency_ms": latency_ms,
            "usage": usage,
            "memo_hit": memo_hit,
            "memo_of": memo_of,
        }
        (settings.grader_capture_dir / f"{call_id}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # capture must never break grading
        pass


class MemoGrader:
    """Wraps any grader with in-memory memoisation and capture writing."""

    def __init__(self, inner: Grader, backend: str):
        self.inner = inner
        self.backend = backend

    async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None) -> GraderOutput:
        links = node_links(curriculum)
        user = _user_content(curriculum, transcript, focus_node_id, prior_context)
        system_text = _system_text(curriculum, links, focus_node_id)
        key = memo_key(self.backend, prompts.PROMPT_VERSION, system_text, user)
        call_id = call_id or new_call_id()

        if not settings.grade_memo:
            return await self.inner.grade(
                curriculum, transcript, focus_node_id=focus_node_id, prior_context=prior_context,
                session_id=session_id, student_id=student_id, call_id=call_id
            )

        cached = grade_memo.get(key)
        if cached:
            output, original_call_id = cached
            _capture(
                session_id=session_id,
                student_id=student_id,
                focus_node_id=focus_node_id,
                call_id=call_id,
                curriculum=curriculum,
                links=links,
                user=user,
                result=output,
                fixes={},
                provider=self.backend,
                model=self.backend,
                request_id=None,
                usage=None,
                latency_ms=0,
                phase="teach_back" if focus_node_id else "diagnostic",
                memo_hit=True,
                memo_of=original_call_id,
            )
            return output

        # Miss: call inner grader with the same call_id
        output = await self.inner.grade(
            curriculum, transcript, focus_node_id=focus_node_id, prior_context=prior_context,
            session_id=session_id, student_id=student_id, call_id=call_id
        )
        grade_memo.put(key, output, call_id)
        return output


# --------------------------------------------------------------------------- #
# Mock
# --------------------------------------------------------------------------- #
_STOP = {
    "the", "and", "that", "with", "from", "this", "when", "than", "then", "into", "only", "over",
    "each", "must", "have", "been", "which", "their", "there", "these", "those", "about", "after",
    "before", "other", "some", "such", "also", "more", "less", "does", "were", "step", "entity",
    "customer", "contract", "revenue", "goods", "services", "service", "good", "performance",
    "obligation", "obligations", "states", "explains", "names", "gives", "least", "mentions",
    "identifies", "distinguishes", "lists", "notes", "describes", "defines",
}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP}


class MockGrader:
    """Keyword-overlap grader. Not clever - just deterministic and free. Emits one claim per
    matched node, cited to that node's own linked passages."""

    async def grade(self, curriculum, transcript, *, focus_node_id, prior_context, session_id, student_id: str = "", call_id: str | None = None) -> GraderOutput:
        links = node_links(curriculum)
        user = _user_content(curriculum, transcript, focus_node_id, prior_context)
        call_id = call_id or new_call_id()
        start = time.perf_counter()
        said = _keywords(transcript)
        verdicts: list[NodeVerdictV2] = []
        claims: list[Claim] = []
        for n in curriculum.tree.nodes:
            target = _keywords(n.title + " " + " ".join(n.rubric))
            if not target:
                continue
            overlap = len(said & target) / len(target)
            if overlap >= 0.45:
                status = NodeStatus.VERIFIED
            elif overlap >= 0.2:
                status = NodeStatus.PARTIAL
            elif n.id == focus_node_id:
                status = NodeStatus.GAP
            else:
                continue
            evidence = " ".join(sorted(said & target))[:120] or "(no matching terms)"
            verdicts.append(
                NodeVerdictV2(
                    node_id=n.id,
                    status=status,
                    confidence=round(min(1.0, 0.5 + overlap), 2),
                    evidence=evidence,
                    rubric_items_met=[i for i, item in enumerate(n.rubric) if said & _keywords(item)],
                )
            )
            claims.append(
                Claim(
                    claim_id=f"c{len(claims) + 1}",
                    quote=evidence,
                    node_id=n.id,
                    judgment=ClaimJudgment.UNSUPPORTED if status == NodeStatus.GAP else ClaimJudgment.ACCURATE,
                    passage_ids=links.ids(n.id)[:1],
                )
            )
        verified = sum(1 for v in verdicts if v.status == NodeStatus.VERIFIED)
        summary = f"[mock] {verified} node(s) verified, {len(verdicts) - verified} partial/gap from keyword overlap."
        result, fixes = _finalise(curriculum, GraderOutput(claims=claims, verdicts=verdicts, summary=summary), links)
        _capture(
            session_id=session_id,
            student_id=student_id,
            focus_node_id=focus_node_id,
            call_id=call_id,
            curriculum=curriculum,
            links=links,
            user=user,
            result=result,
            fixes=fixes,
            provider="mock",
            model="mock",
            request_id=None,
            usage=None,
            latency_ms=round((time.perf_counter() - start) * 1000),
            phase="teach_back" if focus_node_id else "diagnostic",
        )
        return result