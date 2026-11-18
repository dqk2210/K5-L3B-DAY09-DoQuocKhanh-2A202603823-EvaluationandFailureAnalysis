"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, load_spec, per_item


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    import math

    problems: list[str] = []

    for mid, val in (pr.get("metrics") or {}).items():
        if isinstance(val, float) and not math.isfinite(val):
            problems.append(f"metric {mid} is {val} (a mean of NaN/inf is not evidence)")

    items = pr["manifest"].get("items")
    seeds = pr["manifest"].get("seeds") or []
    base_seeds = base["manifest"].get("seeds") or []
    if items is not None and len(pr["rows"]) != items * len(seeds):
        problems.append(f"rows {len(pr['rows'])} != {items} items x {len(seeds)} seeds "
                        f"(rows were dropped or duplicated)")
    if len(pr["rows"]) != len(base["rows"]):
        problems.append(f"rows {len(pr['rows'])} != baseline {len(base['rows'])} "
                        f"(rows were dropped or duplicated)")
    if base_seeds and set(seeds) != set(base_seeds):
        problems.append(f"manifest seeds {seeds} differ from baseline {base_seeds}")

    pr_pair_list = [(r.get("item_id"), r.get("seed")) for r in pr["rows"]]
    pr_pairs = set(pr_pair_list)
    base_pairs = {(r.get("item_id"), r.get("seed")) for r in base["rows"]}
    if len(pr_pair_list) != len(pr_pairs):
        problems.append(f"duplicate (item_id, seed) rows detected ({len(pr_pair_list)} rows vs {len(pr_pairs)} unique)")
    if pr_pairs != base_pairs:
        problems.append("(item, seed) set differs from the baseline (cherry-picked seeds/items)")

    if pr.get("evaluator_failures"):
        problems.append(f"{len(pr['evaluator_failures'])} evaluator failure(s): {pr['evaluator_failures'][0]}")

    row_keys = set().union(*(r.keys() for r in base["rows"]), *(r.keys() for r in pr["rows"]))
    graded = [m["id"] for m in spec.get("metrics", []) if m["id"] in row_keys]
    for r in pr["rows"]:
        missing = [mid for mid in graded if r.get(mid) is None]
        if missing:
            problems.append(f"{r.get('item_id')}@{r.get('seed')}: graded metric(s) {','.join(missing)} are None "
                            f"(a crashed grader must fail the run, not vanish from the mean)")

    if pr["rows"]:
        pr_metrics = pr.get("metrics") or {}
        for mid in graded:
            if mid not in pr_metrics or pr_metrics[mid] is None:
                continue
            vals = [r.get(mid) for r in pr["rows"]]
            if any(v is None for v in vals):
                continue
            expected = sum(bool(v) for v in vals) if mid in ("secret_leak", "approval_bypass") else round(sum(bool(v) for v in vals) / len(vals), 4)
            if isinstance(pr_metrics[mid], (int, float)) and math.isfinite(pr_metrics[mid]) and abs(pr_metrics[mid] - expected) > 1e-3:
                problems.append(f"metric {mid}={pr_metrics[mid]} does not match recomputed rows ({expected})")

    pr_slices = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in pr["rows"]}
    base_slices = {(r.get("item_id"), r.get("seed")): tuple(sorted(r.get("slices") or [])) for r in base["rows"]}
    for pair, tags in pr_slices.items():
        if pair in base_slices and tags != base_slices[pair]:
            problems.append(f"{pair[0]}@{pair[1]}: slice tags {list(tags)} differ from baseline {list(base_slices[pair])} "
                            f"(relabelling an item out of a slice hides its regression)")

    if base_spec is not None:
        if spec.get("eval_set_version") != base_spec.get("eval_set_version"):
            problems.append(f"eval_set_version {spec.get('eval_set_version')} != baseline "
                            f"{base_spec.get('eval_set_version')}: this is a new eval set, not a threshold tweak")
        base_m = {m["id"]: m for m in base_spec.get("metrics", [])}
        for m in base_spec.get("metrics", []):   # a baseline metric may not disappear
            if m["id"] not in {x["id"] for x in spec.get("metrics", [])}:
                problems.append(f"metric {m['id']} disappeared vs base spec")
        for m in spec.get("metrics", []):
            bm = base_m.get(m["id"])
            if bm is None:
                continue
            th, bth = m.get("threshold") or {}, bm.get("threshold") or {}
            if "max" in bth and ("max" not in th or th["max"] > bth["max"]):
                problems.append(f"{m['id']}: max {th.get('max')} loosened or removed vs baseline {bth['max']}")
            if "min" in bth and ("min" not in th or th["min"] < bth["min"]):
                problems.append(f"{m['id']}: min {th.get('min')} loosened or removed vs baseline {bth['min']}")
            if "max_increase" in bth and ("max_increase" not in th or th["max_increase"] > bth["max_increase"]):
                problems.append(f"{m['id']}: max_increase {th.get('max_increase')} loosened or removed vs baseline {bth['max_increase']}")
            if bth.get("no_significant_drop") and not th.get("no_significant_drop"):
                problems.append(f"{m['id']}: no_significant_drop dropped vs base spec (looser)")
            if bm.get("blocking") and not m.get("blocking"):
                problems.append(f"{m['id']}: blocking metric became non-blocking (looser)")
        base_sl = {s["name"]: s for s in base_spec.get("slices", [])}
        for s in base_spec.get("slices", []):    # a baseline slice may not disappear
            if s["name"] not in {x["name"] for x in spec.get("slices", [])}:
                problems.append(f"slice {s['name']} disappeared vs base spec (looser)")
        for s in spec.get("slices", []):
            bs = base_sl.get(s["name"])
            if bs is None:
                continue
            s_min = (s.get("threshold") or s).get("min")
            bs_min = (bs.get("threshold") or bs).get("min")
            if bs_min is not None and (s_min is None or s_min < bs_min):
                problems.append(f"slice {s['name']}: min {s_min} loosened or removed vs baseline {bs_min}")
            if bs.get("no_significant_drop") and not s.get("no_significant_drop"):
                problems.append(f"slice {s['name']}: no_significant_drop dropped vs base spec (looser)")
            if bs.get("blocking") and not s.get("blocking"):
                problems.append(f"slice {s['name']}: blocking slice became non-blocking (looser)")

    return list(dict.fromkeys(problems))   # de-dup, keep order


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices", []):
        name, mid = s["name"], s["metric"]
        a, b = per_item(pr, mid, slice_name=name), per_item(base, mid, slice_name=name)
        keys = sorted(set(a) & set(b))
        if not keys:
            lines.append(f"  slice:{name}/{mid:<15} no items carry this slice -- check the eval set")
            continue
        val = sum(a[k] for k in keys) / len(keys)
        th, verdict, note = s.get("threshold") or s, "ok", ""
        if "min" in th and val < th["min"]:
            verdict = "fail"
        if s.get("no_significant_drop"):
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict == "fail" and s.get("blocking"):
            blocked.append(f"slice:{name}/{mid}")
        label = {"ok": "ok"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        lines.append(f"  slice:{name}/{mid:<15} {val:.3f} (n={len(keys)}) {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
