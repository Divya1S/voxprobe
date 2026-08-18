"""Judge calibration: how often does a human agree with the LLM judge's claims?

`sample` pulls judged claims out of existing analyses (hypothesis verdicts and agent-attributed candidate issues), stratified
between judge-positive and judge-negative, and writes a labelling sheet with the transcript excerpt each claim is about.
A human marks each row agree / disagree / unclear. `score` reads the sheet back and reports agreement and Cohen's κ
(judge vs human on positive/negative), overall and per claim type. Small, honest, and reproducible — the point is a
number a reviewer can check, not a big one.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Settings

_TS = re.compile(r"(\d{1,2}):(\d{2})")


@dataclass
class Claim:
    id: str
    stem: str
    kind: str  # "hypothesis" | "issue"
    claim: str
    judge_positive: bool  # hypothesis observed / issue flagged
    evidence: str
    excerpt: str


def _excerpt(transcript_lines: list[str], evidence: str, width: int = 3) -> str:
    """Lines around the first mm:ss found in the evidence; else the first lines."""
    m = _TS.search(evidence or "")
    if m and transcript_lines:
        target = int(m.group(1)) * 60 + int(m.group(2))
        best_i, best_d = 0, 10**9
        for i, line in enumerate(transcript_lines):
            t = _TS.match(line.strip("[").strip())
            if t:
                d = abs(int(t.group(1)) * 60 + int(t.group(2)) - target)
                if d < best_d:
                    best_i, best_d = i, d
        lo, hi = max(0, best_i - width), min(len(transcript_lines), best_i + width + 1)
        return "\n".join(transcript_lines[lo:hi])
    return "\n".join(transcript_lines[:8])


def _transcript_lines(settings: Settings, stem: str) -> list[str]:
    for cand in (f"{stem}.whisper.md", f"{stem}.md"):
        p = settings.transcripts_dir / cand
        if p.exists():
            return [ln for ln in p.read_text().splitlines() if ln.startswith("[")]
    return []


def collect_claims(settings: Settings, pattern: str = "*.analysis.json") -> list[Claim]:
    claims: list[Claim] = []
    for path in sorted(settings.reports_dir.glob(pattern)):
        stem = path.name.replace(".analysis.json", "")
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        judge = data.get("judge") or {}
        lines = _transcript_lines(settings, stem)
        for i, h in enumerate(judge.get("hypotheses") or []):
            if h.get("observed") not in (True, False):
                continue
            ev = str(h.get("evidence") or "")
            claims.append(
                Claim(
                    f"{stem}#h{i}",
                    stem,
                    "hypothesis",
                    h.get("hypothesis", ""),
                    bool(h["observed"]),
                    ev,
                    _excerpt(lines, ev),
                )
            )
        for i, it in enumerate(judge.get("candidate_issues") or []):
            if it.get("who") != "agent":
                continue
            ev = f"{it.get('timestamp', '')} {it.get('quote', '')}"
            text = f"{it.get('title', '')} — expected: {it.get('expected', '')}"
            claims.append(Claim(f"{stem}#i{i}", stem, "issue", text, True, ev, _excerpt(lines, ev)))
    return claims


def sample(
    settings: Settings, name: str, n: int = 25, seed: int = 0, pattern: str = "*.analysis.json", force: bool = False
) -> Path:
    existing = settings.reports_dir / "calibration" / f"{name}.md"
    if existing.exists() and not force:
        raise FileExistsError(f"{existing} exists (it may hold hand labels) — choose another name or pass force=True")
    claims = collect_claims(settings, pattern)
    rng = random.Random(seed)
    pos = [c for c in claims if c.judge_positive]
    neg = [c for c in claims if not c.judge_positive]
    rng.shuffle(pos)
    rng.shuffle(neg)
    half = n // 2
    picked = pos[:half] + neg[: n - half]
    if len(picked) < n:  # top up from whichever side has more
        rest = [c for c in pos[half:] + neg[n - half :] if c not in picked]
        rng.shuffle(rest)
        picked += rest[: n - len(picked)]
    rng.shuffle(picked)
    out_dir = settings.reports_dir / "calibration"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.json").write_text(json.dumps([asdict(c) for c in picked], indent=2))
    md = [
        f"# Judge calibration sheet — {name}",
        "",
        f"{len(picked)} claims sampled from {len(claims)} ({len(pos)} judge-positive, {len(neg)} judge-negative), seed {seed}.",
        "For each claim, read the excerpt (open the full transcript if needed) and set **Human** to `agree`, `disagree` or `unclear`.",
        "`agree` means: the judge's positive/negative call is right. Then run `voxprobe calibrate score <this file>`.",
        "",
    ]
    for k, c in enumerate(picked, 1):
        md += [
            f"## {k}. `{c.id}` — {c.kind}, judge says **{'POSITIVE' if c.judge_positive else 'negative'}**",
            "",
            f"**Claim:** {c.claim}",
            "",
            f"**Judge evidence:** {c.evidence or '—'}",
            "",
            "```",
            c.excerpt or "(no transcript excerpt)",
            "```",
            "",
            "Human: ",
            "",
        ]
    path = out_dir / f"{name}.md"
    path.write_text("\n".join(md))
    return path


def score(sheet: Path) -> dict:
    text = sheet.read_text()
    blocks = re.split(r"^## \d+\. ", text, flags=re.M)[1:]
    pairs: list[tuple[str, bool, str]] = []  # (kind, judge_positive, human)
    for b in blocks:
        head = b.splitlines()[0]
        kind = "hypothesis" if "— hypothesis" in head else "issue"
        judge_pos = "**POSITIVE**" in head
        m = re.search(r"^Human:\s*(agree|disagree|unclear)", b, flags=re.M | re.I)
        if not m:
            continue
        pairs.append((kind, judge_pos, m.group(1).lower()))
    labelled = [p for p in pairs if p[2] in ("agree", "disagree")]

    def kappa(items: list[tuple[str, bool, str]]) -> float | None:
        # human's positive/negative implied by agree/disagree with the judge's call
        if len(items) < 2:
            return None
        n = len(items)
        jp = [1 if j else 0 for _, j, _ in items]
        hp = [j if h == "agree" else (not j) for _, j, h in items]
        hp = [1 if x else 0 for x in hp]
        po = sum(1 for a, b in zip(jp, hp, strict=True) if a == b) / n
        pj, ph = sum(jp) / n, sum(hp) / n
        pe = pj * ph + (1 - pj) * (1 - ph)
        return None if pe == 1 else round((po - pe) / (1 - pe), 3)

    def summary(items):
        lab = [p for p in items if p[2] in ("agree", "disagree")]
        return {
            "n_labelled": len(lab),
            "n_unclear": sum(1 for p in items if p[2] == "unclear"),
            "agreement": round(sum(1 for p in lab if p[2] == "agree") / len(lab), 3) if lab else None,
            "cohens_kappa": kappa(lab),
        }

    return {
        "sheet": sheet.name,
        "overall": summary(pairs),
        "hypotheses": summary([p for p in pairs if p[0] == "hypothesis"]),
        "issues": summary([p for p in pairs if p[0] == "issue"]),
        "judge_positive_precision": (
            round(sum(1 for _, j, h in labelled if j and h == "agree") / max(1, sum(1 for _, j, _ in labelled if j)), 3)
            if any(j for _, j, _ in labelled)
            else None
        ),
    }
