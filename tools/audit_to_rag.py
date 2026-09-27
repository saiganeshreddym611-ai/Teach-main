#!/usr/bin/env python3
"""Convert the sectioned Audit audio-guide text files into RAG-ready JSONL chunks.

Input: files like `Audit/Chapter 5 Audit Evidence_split_audio.txt`, split into sections by lines
of the form `--- SECTION: <TITLE> ---`.

For each section the script numbers the paragraphs ([P1], [P2], ...) and asks the model to group
consecutive paragraphs into self-contained retrieval chunks and to describe each one (title,
summary, keywords, standards, chunk type, questions it answers). The chunk `text` is always the
original paragraphs, copied verbatim by code. The model only chooses boundaries and writes
metadata, so it cannot change or invent source content.

Output (one record per line, the common `id` / `text` / `metadata` shape that Chroma, LanceDB,
LlamaIndex and LangChain loaders accept):
    <out>/sections/<chapter>/sNN.json   one file per section (the resume cache)
    <out>/chapters/<chapter>.jsonl      one file per chapter
    <out>/audit_corpus.jsonl            everything, with --consolidate
    <out>/manifest.json                 counts, model, source hashes, with --consolidate

Usage:
    python tools/audit_to_rag.py --dry-run                      # show sections and sizes, no model calls
    python tools/audit_to_rag.py --only "Chapter 5"             # one chapter
    python tools/audit_to_rag.py                                # all chapters, resumes where it stopped
    python tools/audit_to_rag.py --workers 3 --consolidate      # faster, then merge into one corpus
    python tools/audit_to_rag.py --no-llm                       # deterministic chunks only (offline)

Model: `gemma4:31b-cloud` through a local Ollama daemon (`ollama signin` once). For Ollama's hosted
API directly, pass --host https://ollama.com --model gemma4:31b and set OLLAMA_API_KEY.

Standard library only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

PIPELINE_VERSION = "2"
REPO = Path(__file__).resolve().parents[1]
DEFAULT_IN = REPO.parent / "Audit"
DEFAULT_OUT = REPO.parent / "Audit_rag"

SECTION_RE = re.compile(r"^-{2,}\s*SECTION:\s*(.*?)\s*-{2,}\s*$", re.M)
FILE_RE = re.compile(r"^Chapter\s+(\d+)\s+(.*?)(?:_split_audio)?\.txt$", re.I)
# Case-sensitive on purpose: "SA 500" / "Section 143(3)" are standards, "as 10" / "section 2.2" are not.
STANDARD_RE = re.compile(
    r"\b(?:SA|SQC|SQM|SRE|SAE|SRS|Ind AS|AS|CARO|Section)\s?\d{1,4}(?:\(\d+\))?(?:\([a-z]\))?(?!\d|\.\d)"
)
CHUNK_TYPES = ["concept", "requirement", "procedure", "example", "test_your_understanding", "summary", "other"]

SCHEMA = {
    "type": "object",
    "properties": {
        "chunks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "para_start": {"type": "integer"},
                    "para_end": {"type": "integer"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "standards": {"type": "array", "items": {"type": "string"}},
                    "chunk_type": {"type": "string", "enum": CHUNK_TYPES},
                    "questions": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["para_start", "para_end", "title", "summary", "keywords",
                             "standards", "chunk_type", "questions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["chunks"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""You prepare CA Final Audit study material for a retrieval (RAG) database.
The input is one section of an audio-guide script, split into numbered paragraphs [P1], [P2], ...

Group consecutive paragraphs into self-contained chunks:
- Each chunk covers one idea and is roughly 150 to 400 words. A short section may be one chunk.
- Keep a list together with the sentence that introduces it.
- Keep a "Test Your Understanding" scenario together with its answer or discussion.
- Chunks must be in order, must not overlap and must cover every paragraph from P1 to the last one.

For each chunk return:
- para_start, para_end: the first and last paragraph numbers in the chunk.
- title: a short descriptive title (at most 10 words).
- summary: one or two sentences using only facts stated in the chunk.
- keywords: 3 to 8 key terms that appear in the chunk.
- standards: standards, sections or rules named in the chunk, written as they appear (e.g. "SA 500", "SQC 1", "Section 143(3)"). Empty list if none.
- chunk_type: one of {", ".join(CHUNK_TYPES)}.
- questions: 2 or 3 questions a student could ask that this chunk answers.

Use only the text given. Do not add facts, standards or examples that are not in the text.
Return only a JSON object: {{"chunks": [ ... ]}}"""


# --------------------------------------------------------------------------- #
# Splitting
# --------------------------------------------------------------------------- #
def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def split_sections(text: str) -> list[tuple[str, str]]:
    parts = SECTION_RE.split(text)
    sections: list[tuple[str, str]] = []
    if parts[0].strip():
        sections.append(("Introduction", parts[0]))
    for title, body in zip(parts[1::2], parts[2::2]):
        if body.strip():
            sections.append((title.strip() or "Untitled", body))
    return sections


def paragraphs(body: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", body.replace("\r\n", "\n")) if p.strip()]


def words(s: str) -> int:
    return len(s.split())


def split_parts(paras: list[str], max_words: int) -> list[list[str]]:
    """Group paragraphs into model-sized parts on paragraph boundaries."""
    parts: list[list[str]] = []
    cur: list[str] = []
    n = 0
    for p in paras:
        w = words(p)
        if cur and n + w > max_words:
            parts.append(cur)
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        parts.append(cur)
    return parts


# --------------------------------------------------------------------------- #
# Model call
# --------------------------------------------------------------------------- #
def ollama_chat(args, messages: list[dict]) -> str:
    body = {
        "model": args.model,
        "messages": messages,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_ctx": args.num_ctx},
    }
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"
    url = args.host.rstrip("/") + "/api/chat"
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
            with urllib.request.urlopen(req, timeout=args.timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
            return (data.get("message") or {}).get("content") or ""
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:
                detail = e.read().decode("utf-8", "replace")[:300]
                raise RuntimeError(f"Ollama HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(5 * (attempt + 1) ** 2)
    raise RuntimeError(f"Ollama unreachable at {url}: {last}")


def extract_json(text: str) -> dict:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t[3:]
        t = t.rstrip().removesuffix("```").strip()
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
    a = t.find("{")
    obj, _ = json.JSONDecoder().raw_decode(t, a if a != -1 else 0)
    if not isinstance(obj, dict) or not isinstance(obj.get("chunks"), list):
        raise ValueError('expected an object with a "chunks" list')
    return obj


def boundary_error(chunks: list[dict], n: int) -> str | None:
    expected = 1
    for i, c in enumerate(chunks):
        s, e = c.get("para_start"), c.get("para_end")
        if not isinstance(s, int) or not isinstance(e, int):
            return f"chunk {i + 1} has non-integer para_start/para_end"
        if s != expected:
            return f"chunk {i + 1} starts at P{s} but should start at P{expected}"
        if e < s or e > n:
            return f"chunk {i + 1} ends at P{e}, outside P{s}..P{n}"
        expected = e + 1
    if expected != n + 1:
        return f"chunks stop at P{expected - 1} but the last paragraph is P{n}"
    return None


def repair(chunks: list[dict], n: int) -> list[dict]:
    """Make boundaries contiguous while keeping the model's metadata."""
    good = [c for c in chunks if isinstance(c.get("para_start"), int) and isinstance(c.get("para_end"), int)]
    good.sort(key=lambda c: (c["para_start"], c["para_end"]))
    out: list[dict] = []
    nxt = 1  # first paragraph not yet covered
    for c in good:
        s, e = max(c["para_start"], 1), min(c["para_end"], n)
        if e < nxt or s > e:
            continue  # empty, or fully covered by earlier chunks
        if s > nxt:  # gap before this chunk
            if out:
                out[-1]["para_end"] = s - 1
            else:
                s = 1
        else:  # overlap: start right after the previous chunk
            s = nxt
        out.append({**c, "para_start": s, "para_end": e})
        nxt = e + 1
    if out:
        out[-1]["para_end"] = n
    return out


def fallback_chunks(paras: list[str], target_words: int = 300) -> list[dict]:
    chunks, start, n = [], 1, 0
    for i, p in enumerate(paras, 1):
        n += words(p)
        if n >= target_words or i == len(paras):
            chunks.append({"para_start": start, "para_end": i, "title": "", "summary": "",
                           "keywords": [], "standards": [], "chunk_type": "other", "questions": []})
            start, n = i + 1, 0
    return chunks


def chunk_part(args, section_title: str, paras: list[str]) -> tuple[list[dict], str]:
    """Return (chunks with para_start/para_end relative to `paras`, llm_status)."""
    if args.no_llm:
        return fallback_chunks(paras), "no_llm"
    numbered = "\n\n".join(f"[P{i}] {p}" for i, p in enumerate(paras, 1))
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Section: {section_title}\nParagraphs: P1 to P{len(paras)}\n\n{numbered}"},
    ]
    parsed: dict | None = None
    for attempt in (1, 2):
        content = ollama_chat(args, messages)
        try:
            parsed = extract_json(content)
            err = boundary_error(parsed["chunks"], len(paras))
        except (ValueError, json.JSONDecodeError) as e:
            parsed, err = None, f"invalid JSON ({e})"
        if err is None:
            return parsed["chunks"], "ok" if attempt == 1 else "ok_retry"
        if attempt == 1:
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"That output has a problem: {err}. Return the full corrected "
                                            f"JSON. Chunks must run in order from P1 to P{len(paras)} "
                                            "with no gaps and no overlaps."},
            ]
    if parsed is not None:
        fixed = repair(parsed["chunks"], len(paras))
        if fixed and boundary_error(fixed, len(paras)) is None:
            return fixed, "repaired"
    return fallback_chunks(paras), "fallback"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def standards_in(text: str, from_model: list[str]) -> list[str]:
    """Regex matches from the text, plus model-named standards that really occur in the text."""
    found = [m.group(0).strip() for m in STANDARD_RE.finditer(text)]
    norm_text = _norm(text)
    found += [s.strip() for s in from_model if isinstance(s, str) and s.strip() and _norm(s) in norm_text]
    out, seen = [], set()
    for s in found:
        k = _norm(s)
        if k not in seen:
            seen.add(k)
            out.append(s)
    return out


def clean_list(v, limit: int) -> list[str]:
    return [str(x).strip() for x in (v or []) if str(x).strip()][:limit]


def process_section(args, job: dict) -> dict:
    out_file: Path = job["out_file"]
    body_sha = sha(job["body"])
    if out_file.exists() and not args.force:
        try:
            cached = json.loads(out_file.read_text(encoding="utf-8"))
            if (cached.get("section_sha256") == body_sha and cached.get("model") == job["model_tag"]
                    and cached.get("pipeline_version") == PIPELINE_VERSION):
                return {"job": job, "cached": True, "records": cached["records"], "statuses": cached["statuses"]}
        except (json.JSONDecodeError, KeyError):
            pass

    paras = paragraphs(job["body"])
    parts = split_parts(paras, args.max_words)
    records, statuses = [], []
    chunk_no = 0
    offset = 0  # paragraph offset of this part within the section
    for part_no, part in enumerate(parts, 1):
        chunks, status = chunk_part(args, job["section_title"], part)
        statuses.append(status)
        for c in chunks:
            chunk_no += 1
            text = "\n\n".join(part[c["para_start"] - 1 : c["para_end"]])
            ctype = c.get("chunk_type") if c.get("chunk_type") in CHUNK_TYPES else "other"
            records.append({
                "id": f"{job['id_prefix']}.c{chunk_no:03d}",
                "text": text,
                "metadata": {
                    "subject": args.subject,
                    "doc_type": "audio_script",
                    "chapter_no": job["chapter_no"],
                    "chapter": job["chapter_title"],
                    "section_no": job["section_no"],
                    "section": job["section_title"],
                    "part_no": part_no,
                    "chunk_no": chunk_no,
                    "para_start": offset + c["para_start"],
                    "para_end": offset + c["para_end"],
                    "title": str(c.get("title") or job["section_title"]).strip(),
                    "summary": str(c.get("summary") or "").strip(),
                    "keywords": clean_list(c.get("keywords"), 8),
                    "standards": standards_in(text, c.get("standards") or []),
                    "chunk_type": ctype,
                    "questions": clean_list(c.get("questions"), 3),
                    "word_count": words(text),
                    "source_file": job["source_file"],
                    "text_sha256": sha(text),
                    "llm_status": status,
                    "model": job["model_tag"],
                    "pipeline_version": PIPELINE_VERSION,
                },
            })
        offset += len(part)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps({
        "source_file": job["source_file"],
        "section_no": job["section_no"],
        "section_title": job["section_title"],
        "section_sha256": body_sha,
        "model": job["model_tag"],
        "pipeline_version": PIPELINE_VERSION,
        "statuses": statuses,
        "records": records,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"job": job, "cached": False, "records": records, "statuses": statuses}


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def collect_jobs(args) -> tuple[list[dict], dict[str, dict]]:
    files = sorted(Path(args.input).glob("*.txt"))
    if args.only:
        files = [f for f in files if args.only.lower() in f.name.lower()]
    if not files:
        sys.exit(f"No .txt files found in {args.input}" + (f" matching '{args.only}'" if args.only else ""))
    model_tag = "none" if args.no_llm else args.model
    jobs, chapters = [], {}
    for f in files:
        m = FILE_RE.match(f.name)
        chapter_no = int(m.group(1)) if m else 0
        chapter_title = (m.group(2) if m else f.stem).strip()
        slug = f"ch{chapter_no:02d}-{slugify(chapter_title)}"[:80]
        text = f.read_text(encoding="utf-8", errors="replace")
        sections = split_sections(text)
        chapters[slug] = {"chapter_no": chapter_no, "chapter": chapter_title, "source_file": f.name,
                          "source_sha256": sha(text), "sections": len(sections)}
        for i, (title, body) in enumerate(sections, 1):
            jobs.append({
                "source_file": f.name, "chapter_no": chapter_no, "chapter_title": chapter_title,
                "chapter_slug": slug, "section_no": i, "section_count": len(sections),
                "section_title": title, "body": body, "model_tag": model_tag,
                "id_prefix": f"{slugify(args.subject)}.ch{chapter_no:02d}.s{i:02d}",
                "out_file": Path(args.out) / "sections" / slug / f"s{i:02d}.json",
            })
    return jobs, chapters


def dry_run(args, jobs: list[dict]) -> None:
    total_parts = 0
    for j in jobs:
        paras = paragraphs(j["body"])
        parts = split_parts(paras, args.max_words)
        total_parts += len(parts)
        print(f"ch{j['chapter_no']:02d} s{j['section_no']:02d}/{j['section_count']:02d} "
              f"{words(j['body']):>6} words {len(paras):>4} paras {len(parts)} part(s)  {j['section_title'][:60]}")
    print(f"\n{len(jobs)} sections, {total_parts} model calls (plus retries) with --max-words {args.max_words}")


def write_chapters(args, chapters: dict[str, dict], results: dict[str, list[dict]]) -> None:
    for slug, recs in results.items():
        recs.sort(key=lambda r: (r["metadata"]["section_no"], r["metadata"]["chunk_no"]))
        path = Path(args.out) / "chapters" / f"{slug}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def consolidate(args, chapters: dict[str, dict]) -> None:
    out = Path(args.out)
    chapter_files = sorted((out / "chapters").glob("*.jsonl"))
    records = []
    for p in chapter_files:
        records += [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    records.sort(key=lambda r: (r["metadata"]["chapter_no"], r["metadata"]["section_no"], r["metadata"]["chunk_no"]))
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        sys.exit("Duplicate chunk ids found; not writing the consolidated corpus.")
    with (out / "audit_corpus.jsonl").open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    statuses: dict[str, int] = {}
    per_chapter: dict[str, dict] = {}
    for r in records:
        md = r["metadata"]
        statuses[md["llm_status"]] = statuses.get(md["llm_status"], 0) + 1
        ch = per_chapter.setdefault(md["source_file"], {"chapter_no": md["chapter_no"], "chapter": md["chapter"],
                                                        "sections": set(), "chunks": 0})
        ch["sections"].add(md["section_no"])
        ch["chunks"] += 1
    for slug, info in chapters.items():  # source hashes are known for files seen in this run
        if info["source_file"] in per_chapter:
            per_chapter[info["source_file"]]["source_sha256"] = info["source_sha256"]
    for ch in per_chapter.values():
        ch["sections"] = len(ch["sections"])
    (out / "manifest.json").write_text(json.dumps({
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subject": args.subject,
        "pipeline_version": PIPELINE_VERSION,
        "models": sorted({r["metadata"]["model"] for r in records}),
        "chunk_count": len(records),
        "chunk_llm_status": statuses,
        "chapters": per_chapter,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"consolidated {len(records)} chunks from {len(chapter_files)} chapter files -> {out / 'audit_corpus.jsonl'}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(DEFAULT_IN), help=f"folder of .txt files (default {DEFAULT_IN})")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"output folder (default {DEFAULT_OUT})")
    ap.add_argument("--only", help="process files whose name contains this text, e.g. 'Chapter 5 '")
    ap.add_argument("--subject", default="Audit")
    ap.add_argument("--model", default=os.environ.get("AUDIT_RAG_MODEL", "gemma4:31b-cloud"))
    ap.add_argument("--host", default=os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
    ap.add_argument("--api-key", default=os.environ.get("OLLAMA_API_KEY"), help="only for --host https://ollama.com")
    ap.add_argument("--max-words", type=int, default=1500, help="words per model call; longer sections are split")
    ap.add_argument("--num-ctx", type=int, default=32768)
    ap.add_argument("--timeout", type=int, default=600, help="seconds per model call")
    ap.add_argument("--workers", type=int, default=1, help="sections processed in parallel")
    ap.add_argument("--force", action="store_true", help="redo sections that are already converted")
    ap.add_argument("--no-llm", action="store_true", help="deterministic ~300-word chunks, no metadata")
    ap.add_argument("--dry-run", action="store_true", help="list sections and model calls, write nothing")
    ap.add_argument("--consolidate", action="store_true", help="also merge all chapters into audit_corpus.jsonl")
    args = ap.parse_args()
    if not args.host.startswith("http"):
        args.host = "http://" + args.host

    jobs, chapters = collect_jobs(args)
    if args.dry_run:
        dry_run(args, jobs)
        return 0

    print(f"{len(jobs)} sections from {len(chapters)} file(s) -> {args.out}  "
          f"(model: {'none' if args.no_llm else args.model} @ {args.host})")
    results: dict[str, list[dict]] = {slug: [] for slug in chapters}
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(process_section, args, j): j for j in jobs}
        for fut in as_completed(futures):
            j = futures[fut]
            tag = f"ch{j['chapter_no']:02d} s{j['section_no']:02d}/{j['section_count']:02d}"
            try:
                res = fut.result()
            except Exception as e:
                failed += 1
                print(f"[{tag}] FAILED {j['section_title'][:50]}: {e}")
                continue
            results[j["chapter_slug"]].extend(res["records"])
            how = "cached" if res["cached"] else ",".join(res["statuses"])
            print(f"[{tag}] {len(res['records']):>3} chunks ({how})  {j['section_title'][:60]}")

    complete = {slug: recs for slug, recs in results.items()
                if not any(j["chapter_slug"] == slug and not j["out_file"].exists() for j in jobs)}
    write_chapters(args, chapters, complete)
    if failed:
        print(f"\n{failed} section(s) failed. Re-run the same command to retry only those.")
    if args.consolidate:
        if failed:
            print("Skipping --consolidate until every section succeeds.")
        else:
            consolidate(args, chapters)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
