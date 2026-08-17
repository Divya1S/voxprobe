from pathlib import Path

from voxprobe.calibrate import score

SHEET = """# Judge calibration sheet — t

## 1. `a#h0` — hypothesis, judge says **POSITIVE**

**Claim:** x

Human: agree

## 2. `a#h1` — hypothesis, judge says **negative**

Human: agree

## 3. `b#i0` — issue, judge says **POSITIVE**

Human: disagree

## 4. `b#h2` — hypothesis, judge says **negative**

Human: unclear

## 5. `c#h0` — hypothesis, judge says **POSITIVE**

Human: agree
"""


def test_score_reports_agreement_kappa_and_precision(tmp_path: Path):
    p = tmp_path / "sheet.md"
    p.write_text(SHEET)
    s = score(p)
    assert s["overall"]["n_labelled"] == 4 and s["overall"]["n_unclear"] == 1
    assert s["overall"]["agreement"] == 0.75
    assert s["hypotheses"]["agreement"] == 1.0
    assert s["issues"]["agreement"] == 0.0
    # judge positives labelled: h0 agree, i0 disagree, c#h0 agree -> precision 2/3
    assert s["judge_positive_precision"] == 0.667
    assert -1.0 <= s["overall"]["cohens_kappa"] <= 1.0
