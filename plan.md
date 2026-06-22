# Plan: Replace AOM `inspect` with in-memory dav1d metadata extraction

## Implementation status — COMPLETE ✅

All phases implemented and validated against `test/0018.json`:

- **Phase 0** — dav1d builds via meson/ninja; baseline captured.
- **Phase 1** — flag-gated inspection callback (`Dav1dSettings.inspect_cb`) + ctypes binding.
- **Phase 2** — full-frame 4×4 `refmvs_block` harvest (the drop-in granularity).
- **Phase 3** — `main.py` rewired to `dav1d_inspect.iter_frames`; AOM JSON / `ijson` /
  tempdir / `cv2` probe / `av1_parser` removed (order hints now from dav1d `refpoc`).
- **Multi-threading** — `--threads` (tile + frame threading); out-of-order frames
  reordered by a decode-order index.
- **C fast path** — `src/av1of_inspect_shim.c` (`libav1of_inspect`) builds the per-frame
  arrays in C, GIL-free, so the threaded decode scales to the decoder's limit (~73 fps
  / ~1.5 s for `0018.ivf`, ~3% off the raw dav1d decode floor) instead of being pinned by
  per-frame Python work. `dav1d_inspect.py` falls back to the ctypes callback if unbuilt.
- **Phase 5** — AOM retired from `setup.sh`; dav1d pinned (`14c73c7d`) + patch persisted
  in `patches/dav1d-inspection.patch`; `ijson` moved to dev deps; README updated.

**Validation:** `motion_vectors` 100% bit-exact, `reference_map` 100%, `block_size`
100% on all inter frames (intra/key frames carry no dav1d block grid). Resolved the
`INVALID_MV` sentinel, ref-index encoding (already matches AOM), and the dav1d→AOM
`BlockSize` LUT. See `test/validate_dav1d_vs_json.py`.

**Speed:** end-to-end ~**29× faster** than the AOM-inspect pipeline (~49 s → ~1.7 s for
`0018.ivf`), the in-memory path eliminating the ~300 MB JSON disk round-trip.

> Known limitation: intra/key frames don't expose a 4×4 block grid in dav1d (it only
> exists for inter prediction), so their `block_map` differs from AOM — irrelevant for
> motion extraction (key frames have zero motion). The threaded path collects frames in
> memory before reordering, so peak memory scales with clip length.

## 1. Goal

Replace the current AOM `inspect.c` → JSON-on-disk → re-read pipeline with a
**dav1d-based decoder that returns block metadata directly in memory as NumPy
arrays**. This removes the two biggest costs in the current pipeline:

- writing a huge JSON to disk (the 13.9 MB `test/0018.ivf` produces a
  **266 MB** `test/0018.json`), and
- parsing that JSON back with `ijson`.

The minimal deliverable is a function that, for each decoded frame, yields:

| Output           | AOM `inspect` field | Shape (4×4 grid)      | Source in dav1d                      |
| ---------------- | ------------------- | --------------------- | ------------------------------------ |
| `motion_vectors` | `motionVectors`     | `(H/4, W/4, 4)` int16 | `refmvs_block.mv.mv[0/1].{x,y}`      |
| `reference_map`  | `referenceFrame`    | `(H/4, W/4, 2)` int8  | `refmvs_block.ref.ref[0/1]`          |
| `block_map`      | `blockSize`         | `(H/4, W/4)` uint8    | `refmvs_block.bs` (remapped — §3.4)  |

The **block map is AOM's `blockSize` layer** — the per-4×4 block partition size
(`BLOCK_4X4` … `BLOCK_128X128`), which `inspect.c` emits via `block_size_map`
(`inspect.c:173`, `offsetof(insp_mi_data, bsize)`).

plus per-frame scalars (`frame_offset`/order hint, `frame_type`, `refidx[7]`,
`refpoc[7]`, width, height) that today require a *second* pass via
`src/modules/av1_parser.py`.

---

## 2. How the current pipeline works (what we are replacing)

```
main.py
 ├─ utils.generate_inspect_json()        # shells out to AOM inspect, writes inspect.json
 ├─ cv2.VideoCapture                      # gets total_frames / width / height
 ├─ av1_parser.get_frame_ref_order_hints  # 2nd parse of the bitstream (pure-Python OBU reader)
 └─ for each frame in ijson.items(inspect.json):
       json_processing.get_motion_vectors(frame_data, ...)  # builds NumPy arrays
       flow_io.writeFlowFile(...)                            # writes .flo5
```

`get_motion_vectors` (src/modules/json_processing.py) consumes exactly three
JSON fields per frame:

- `motionVectors` → `(270, 480, 4)` for `0018.ivf` (1080×1920 ⇒ H/4 × W/4, 4
  values = `[mv0.col, mv0.row, mv1.col, mv1.row]`, units = 1/8 pel, divided by 8
  in Python).
- `referenceFrame` → `(270, 480, 2)` = `[ref_frame[0], ref_frame[1]]`, values in
  `-1..7` (−1 = none, 0 = INTRA, 1..7 = LAST..ALTREF).
- (`referenceFrameMap` is a constant enum dict; `config.MI_SIZE = 4`.)

The order-hint / reference info (`av1_parser.get_frame_ref_order_hints`) is a
separate custom OBU parser used only to compute temporal distances during
`linear_interpolation`.

### Why inspect.c produces these
`src/third_parties/aom/examples/inspect.c` walks `frame_data.mi_grid`
(`insp_mi_data` per 4×4 MI unit) and dumps `mi->mv[0/1].{col,row}` and
`mi->ref_frame[0/1]` (lines 444–460, 408–420). dav1d has a structurally
identical grid — see below.

---

## 3. dav1d feasibility findings (verified against source)

dav1d does **not** expose block metadata through its public API, but it keeps it
internally in a form that maps cleanly to the AOM grid.

### 3.1 The right structure: `refmvs_block` (4×4, dual-ref) — *drop-in*
`src/third_parties/dav1d/src/refmvs.h:61`
```c
PACKED(typedef struct refmvs_block {
    refmvs_mvpair mv;   // mv.mv[0], mv.mv[1]; each is union mv { int16_t y, x; }
    refmvs_refpair ref; // ref.ref[0], ref.ref[1]  (int8_t)
    uint8_t bs, mf;     // bs = block-size index (the block map), mf = mode flags
}) ALIGN(refmvs_block, 4);   // CHECK_SIZE 12 bytes
```
This is a **per-4×4** record carrying **two** MVs, **two** ref indices, and the
**block size** (`bs`) — an exact analogue of AOM's `insp_mi_data`
(`mv[0/1]`, `ref_frame[0/1]`, `bsize`). It supplies all three required outputs
(motion vectors, reference map, block map = `blockSize`). Choosing this source
keeps the existing `(H/4, W/4, 4)`/`(H/4, W/4, 2)` shapes and the MI_SIZE=4
upscale path **unchanged**.

⚠️ **Lifetime caveat:** `rf->r` is only a **35-row sliding window**
(`refmvs.c:660,829` — `35 * 2 * n_blocks`), reused per superblock-row, *not* a
persisted full-frame buffer. To capture a whole frame we must harvest each
SB-row as it is produced, at the point dav1d already iterates it:
`dav1d_refmvs_save_tmvs(...)` (`src/decode.c:2723` and `:3228`).

### 3.2 The simple fallback: `f->mvs` (8×8, single-ref) — *lossy*
`src/decode.c:3573,3578` — `f->mvs` is a persisted full-frame
`refmvs_temporal_block` array (`mv` + `uint8_t ref`, `refmvs.h:43`), but only
**8×8** granularity and **one** MV/ref per block (the projectable one). Easy to
grab after frame decode (`c->refs[slot].refmvs`), but it is **not** a drop-in:
downstream shapes and the dual-direction logic would change.

> **Decision point (recommended: 4×4 `refmvs_block`).** The 4×4 path is a true
> drop-in for the existing NumPy pipeline and matches `0018.json`. The 8×8 path
> is simpler to wire but lossy and would force downstream changes. Plan below
> assumes the 4×4 path; the 8×8 path is documented as a fast first milestone.

### 3.3 Per-frame scalars come free from the public API
`include/dav1d/headers.h` `Dav1dFrameHeader`: `frame_offset` (order hint /
POC), `frame_type`, `refidx[7]`. `Dav1dSequenceHeader.order_hint_n_bits`.
Reference POCs live in `c->refs[].refpoc[7]` (`src/internal.h:168`). This means
**`src/modules/av1_parser.py` can be retired** — dav1d gives order hints and
ref order hints natively in the same decode pass.

### 3.4 Value mapping (to verify against `test/0018.json`)
- MV units: dav1d `mv` is 1/8-pel — same as AOM. Emit raw int16; keep the
  Python `/8`. Note `mv` field order is `{y, x}`; AOM emits `[col(x), row(y)]`,
  so write `[mv.x, mv.y, ...]` to preserve channel-0 = horizontal.
- `INVALID_MV == 0x80008000` (`refmvs.h:40`) marks "no MV" — map to 0 to match
  AOM's `[0,0]` for intra blocks.
- Reference indices: `refmvs_refpair.ref` is offset-encoded
  (comment: "`[0] = 0: intra=1`, `[1] = -1: comp=0`"). The exact offset vs.
  AOM's `-1/0/1..7` convention **must be validated** by diffing against
  `0018.json` (see Phase 4).
- **Block size (`bs` → `blockSize`)**: dav1d's `enum BlockSize`
  (`src/levels.h:158`) is **reverse-ordered** from AOM's `block_size_map`
  (`BS_128x128 = 0 … BS_4x4 = 21` vs AOM `BLOCK_4X4 = 0 …`). Both enumerate the
  **same 22 partition sizes**, so a static 22-entry lookup table
  (`dav1d bs → AOM BLOCK_* value`) gives an exact bijection. Build this LUT once
  and apply it when filling `block_map`, so values match `0018.json`'s
  `blockSize` exactly.

---

## 4. Proposed architecture

```
libdav1d (patched, built via meson as shared lib)
  └─ NEW inspection hook (build-flag gated, analogous to AOM CONFIG_INSPECTION)
       • allocates a full-frame refmvs_block grid (iw4 × ih4) per frame
       • fills it from each SB-row inside the save_tmvs path
       • fires Dav1dSettings.inspect_cb(cookie, Dav1dInspect*) at frame complete
            ↓ (ctypes, zero-copy via buffer protocol)
src/modules/dav1d_inspect.py   (NEW) — ctypes binding
  • decode IVF in memory, yield per-frame dict of NumPy arrays + scalars
            ↓
src/modules/json_processing.get_motion_vectors(...)  (UNCHANGED interface)
            ↓
main.py loop (simplified: no tempdir, no ijson, no av1_parser, no cv2 probe)
```

### Binding choice
**ctypes against a patched `libdav1d.so/.dylib`** (no extra Python build step;
the only compiled artifact is dav1d itself, which we already build). The C
inspection struct is plain C; NumPy arrays are created with
`np.frombuffer(...)` over the callback buffer (one copy per frame so the array
outlives dav1d's buffer reuse). `cffi` is an acceptable alternative if a typed
header is preferred.

### dav1d patch surface (minimal, isolated)
1. `include/dav1d/dav1d.h`: add `Dav1dInspectData` struct + a
   `void (*inspect_cb)(void *cookie, const Dav1dInspectData*)` and `cookie`
   field in `Dav1dSettings` (guarded so ABI stays optional).
2. `src/decode.c`: in/after the `save_tmvs` per-SB-row loop, copy that row's
   `refmvs_block`s into a frame-sized scratch buffer; at frame completion call
   the callback with grid pointer, stride, `iw4/ih4`, and the scalars.
3. `meson_options.txt` + `meson.build`: a `enable_inspection` option so the
   patch compiles out by default and upstream rebases stay clean.

---

## 5. Implementation phases

**Phase 0 — Build dav1d & baseline (no code change)**
- Update `setup.sh`: clone dav1d, `meson setup build -Denable_inspection=true`,
  `ninja -C build`. Keep AOM build temporarily for parity testing.
- Capture a baseline: decode `0018.ivf` with stock dav1d (`tools/dav1d`) to
  confirm it decodes and measure decode-only fps.

**Phase 1 — 8×8 fallback spike (fast, proves the binding end-to-end)**
- Add the callback firing `f->mvs` (8×8 temporal) + scalars.
- Write `dav1d_inspect.py` ctypes binding; yield NumPy arrays for one frame.
- Validates: build flag, callback ABI, ctypes buffer→NumPy, frame iteration.

**Phase 2 — 4×4 `refmvs_block` harvest (the real drop-in)**
- Allocate full-frame grid; copy each SB-row in the `save_tmvs` path.
- Emit `motion_vectors (H/4,W/4,4)`, `reference_map (H/4,W/4,2)`,
  `block_map (H/4,W/4)` (= AOM `blockSize`, via the §3.4 LUT) + scalars.

**Phase 3 — Python integration**
- New `src/modules/dav1d_inspect.py`: `iter_frames(ivf_path) -> Iterator[dict]`.
- Rewrite `main.py` loop to consume it; drop `generate_inspect_json`, `ijson`,
  the `tempfile`, the `cv2` size probe, and `av1_parser` (order hints now from
  the decoder). Keep `get_motion_vectors` and `writeFlowFile` untouched.

**Phase 4 — Correctness validation (gate before deleting AOM path)**
- Diff dav1d output vs. `test/0018.json` field-by-field for several frames:
  MV values, ref-index encoding, `blockSize` LUT, intra/`INVALID_MV` handling,
  grid dims, order-hint unwrapping. Resolve the ref-index and block-size
  mappings here.
- Acceptance: motion fields and resulting `.flo5` match the AOM-based output
  within tolerance (ideally identical for MV; ref mapping exact).

**Phase 5 — Cleanup & docs**
- Remove AOM from `setup.sh`/`get_version`, update `README.md`, `pyproject`
  if needed; record the dav1d pin/patch.

---

## 6. Risks & open questions

- **Ref-index encoding** (`refmvs_refpair`) vs AOM `-1/0/1..7` — must be mapped;
  validated in Phase 4.
- **`refmvs_block` is decode-internal** — relying on it couples us to a dav1d
  version. Mitigation: pin a dav1d commit; keep the patch tiny and flag-gated.
- **Threading**: `n_frame_threads > 1` duplicates the `r` buffer and reorders
  frame completion. Start single-threaded; revisit threaded harvesting for
  max throughput once correct.
- **MV completeness**: the 4×4 `r` window holds the spatial MV field used for
  prediction; confirm it carries a value for every inter block the AOM grid
  reports (Phase 4 diff will surface gaps).
- **Show-existing-frame / non-shown frames**: ensure frame iteration and
  order-hint unwrapping match the existing `unwrapping_dict` logic.

---

## 7. Out of scope (for the minimal version)
Other AOM inspect layers (`blockSize` string maps, transform/prediction modes,
segmentation, CDEF, palette, etc.). Only block map, motion vectors, and
reference map are required.
