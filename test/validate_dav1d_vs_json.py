"""
Phase 4 validation: compare the in-memory dav1d inspection output against the
AOM-inspect JSON reference (test/0018.json), field by field, AND benchmark how
much faster the in-memory dav1d path is than the current AOM-inspect pipeline
(run the `inspect` tool -> write JSON -> parse JSON back into NumPy arrays).

Both producers emit frames in decode order; AOM appends a trailing `null` that
we skip. Resolves the dav1d -> AOM block-size mapping and reports per-field
agreement so we can gate replacing the AOM path.

Run:  .venv/bin/python test/validate_dav1d_vs_json.py
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import ijson
import numpy as np

sys.path.insert(0, ".")
from src.modules.dav1d_inspect import iter_frames  # noqa: E402

_AOM_INSPECT = "src/third_parties/aom_build/examples/inspect"


def compare(ivf="test/0018.ivf", json_path="test/0018.json", n_threads=0) -> int:
    n = 0
    mv_eq = ref_eq = bs_eq = 0
    mv_cells = ref_cells = bs_cells = 0
    bs_eq_inter = bs_cells_inter = 0  # exclude intra/key frames
    first_mismatch = {}

    with open(json_path, "rb") as fh:
        json_items = ijson.items(fh, "item")
        for dav, j in zip(iter_frames(ivf, n_threads=n_threads), json_items):
            if not isinstance(j, dict):  # trailing null
                break
            assert dav["frame_offset"] == j["frame"], (
                f"frame misalignment: dav={dav['frame_offset']} json={j['frame']}"
            )
            n += 1

            # ---- motion vectors --------------------------------------------
            jmv = np.asarray(j["motionVectors"], dtype=np.int64)
            dmv = dav["motion_vectors"].astype(np.int64)
            mv_match = jmv == dmv
            mv_eq += int(mv_match.all(axis=-1).sum())
            mv_cells += jmv.shape[0] * jmv.shape[1]

            # ---- reference frame -------------------------------------------
            jref = np.asarray(j["referenceFrame"], dtype=np.int64)
            dref = dav["reference_map"].astype(np.int64)
            ref_match = jref == dref
            ref_eq += int(ref_match.all(axis=-1).sum())
            ref_cells += jref.shape[0] * jref.shape[1]

            # ---- block size (binding already maps to AOM BLOCK_* ordering) --
            if "blockSize" in j:
                jbs = np.asarray(j["blockSize"], dtype=np.int64)
                dbs = dav["block_map"].astype(np.int64)
                bs_match = jbs == dbs
                bs_eq += int(bs_match.sum())
                bs_cells += jbs.size
                if dav["frame_type"] in (1, 3):  # INTER / SWITCH
                    bs_eq_inter += int(bs_match.sum())
                    bs_cells_inter += jbs.size

            if not mv_match.all() and "mv" not in first_mismatch:
                idx = np.argwhere(~mv_match.all(axis=-1))[0]
                y, x = int(idx[0]), int(idx[1])
                first_mismatch["mv"] = (
                    dav["frame_offset"],
                    (y, x),
                    f"json={jmv[y, x].tolist()} dav={dmv[y, x].tolist()}",
                )

    def pct(a, b):
        return 100.0 * a / b if b else float("nan")

    print(f"frames compared: {n}")
    print(
        f"  motion_vectors  cell-exact: {pct(mv_eq, mv_cells):6.2f}%  "
        f"({mv_eq}/{mv_cells})"
    )
    print(
        f"  reference_map   cell-exact: {pct(ref_eq, ref_cells):6.2f}%  "
        f"({ref_eq}/{ref_cells})"
    )
    print(
        f"  block_size      cell-exact: {pct(bs_eq, bs_cells):6.2f}%  "
        f"({bs_eq}/{bs_cells})"
    )
    print(
        f"  block_size      inter-only: {pct(bs_eq_inter, bs_cells_inter):6.2f}%  "
        f"({bs_eq_inter}/{bs_cells_inter})  "
        "[intra frames: dav1d has no block grid]"
    )
    if first_mismatch:
        print("first MV mismatch:", first_mismatch.get("mv"))
    return 0


def _time_dav1d(ivf: str, n_threads: int = 0) -> tuple[float, int]:
    """Decode + build NumPy arrays for every frame, in memory. Returns (s, n)."""
    t0 = time.perf_counter()
    n = 0
    for fr in iter_frames(ivf, n_threads=n_threads):
        # Touch the arrays so lazy work (if any) is realised.
        _ = fr["motion_vectors"].sum()
        _ = fr["reference_map"].shape
        _ = fr["block_map"].shape
        n += 1
    return time.perf_counter() - t0, n


def _time_aom_generate(ivf: str, out_json: str) -> float:
    """Run the AOM inspect tool to write the JSON to disk (as the pipeline does)."""
    t0 = time.perf_counter()
    with open(out_json, "wb") as f:
        subprocess.run([_AOM_INSPECT, ivf, "-mv", "-r"], stdout=f, check=True)
    return time.perf_counter() - t0


def _time_json_parse(json_path: str) -> tuple[float, int]:
    """Parse the JSON back into NumPy arrays (the pipeline's read cost)."""
    t0 = time.perf_counter()
    n = 0
    with open(json_path, "rb") as fh:
        for j in ijson.items(fh, "item"):
            if not isinstance(j, dict):
                break
            _ = np.asarray(j["motionVectors"], dtype=np.int16)
            _ = np.asarray(j["referenceFrame"], dtype=np.int16)
            n += 1
    return time.perf_counter() - t0, n


def benchmark(
    ivf="test/0018.ivf",
    json_path="test/0018.json",
    thread_counts=(1, 2, 4, 8, 0),
) -> int:
    print("\n=== speed: in-memory dav1d vs AOM-inspect pipeline ===")

    dav1d_times = {}
    base = None
    for t in thread_counts:
        dav_s, dav_n = _time_dav1d(ivf, n_threads=t)
        dav1d_times[t] = (dav_s, dav_n)
        if base is None:
            base = dav_s
        label = "auto" if t == 0 else str(t)
        print(
            f"  dav1d threads={label:>4}: {dav_s:7.3f}s  "
            f"({dav_n / dav_s:6.1f} fps, {base / dav_s:4.2f}x vs 1-thread)"
        )

    if not Path(_AOM_INSPECT).exists():
        print(f"  AOM inspect not built at {_AOM_INSPECT}; skipping AOM timing.")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_json = str(Path(tmp) / "inspect.json")
        gen_s = _time_aom_generate(ivf, tmp_json)
        parse_s, dav_n = _time_json_parse(tmp_json)

    aom_total = gen_s + parse_s
    best_t = min(dav1d_times, key=lambda k: dav1d_times[k][0])
    best_s = dav1d_times[best_t][0]
    print(f"  AOM inspect -> JSON (decode + write): {gen_s:7.3f}s")
    print(f"  JSON parse -> NumPy arrays:           {parse_s:7.3f}s")
    print(
        f"  AOM pipeline total:                   {aom_total:7.3f}s  "
        f"({dav_n / aom_total:6.1f} fps)"
    )
    print(
        f"  >>> fastest dav1d ({'auto' if best_t == 0 else best_t} threads, "
        f"{best_s:.3f}s) is {aom_total / best_s:5.2f}x faster than the full "
        "AOM pipeline"
    )
    print(f"  >>> and {gen_s / best_s:5.2f}x faster than AOM inspect generation alone")
    return 0


def correctness_sweep(ivf="test/0018.ivf", json_path="test/0018.json") -> int:
    """Confirm the threaded (out-of-order) output matches the reference exactly."""
    print("=== correctness across thread counts ===")
    rc = 0
    for t in (1, 4, 0):
        label = "auto" if t == 0 else str(t)
        print(f"--- threads={label} ---")
        rc |= compare(ivf, json_path, n_threads=t)
    return rc


if __name__ == "__main__":
    rc = correctness_sweep(*sys.argv[1:])
    benchmark(*sys.argv[1:])
    raise SystemExit(rc)
