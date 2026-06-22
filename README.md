# AV1-Optical-Flow

Extract and pre-process motion vectors from AV1 bitstreams for fast and cheap optical flow estimation.

> AV1 Motion Vector Fidelity and Application for Efficient Optical Flow
> [Julien Zouein](https://github.com/zwayn), [Vibhoothi](https://github.com/vibhoothi), Anil Kokaram
> Picture Coding Symposium (PCS) 2025

<p align="center">
<video width="720" src="https://github.com/user-attachments/assets/895cdddc-657e-43a3-8b76-e7e675998b87" autoplay muted loop playsinline>
   Your browser does not support the video tag.
</video>
</p>

## Overview

AV1-Optical-Flow extracts the motion vectors that the AV1 encoder already
computes during compression and converts them into standard optical flow fields
(`.flo5` format).  Because the motion information is a free by-product of
video encoding, this approach is orders of magnitude faster than running a
dedicated optical flow network, making it suitable for real-time or
large-scale video analysis pipelines.

The pipeline:

1. **Decodes** the AV1 bitstream with [dav1d](https://code.videolan.org/videolan/dav1d),
   patched with a per-frame inspection callback that exposes the decoder's
   internal block metadata (motion vectors, reference indices, block sizes, and
   reference order hints) **directly in memory as NumPy arrays** — no JSON, no
   disk round-trip. Decoding is multi-threaded.
2. **Post-processes** the motion vectors with optional linear interpolation,
   upscaling, and bidirectional filling.
3. **Writes** the result as `.flo5` (HDF5-compressed) flow files.

> Earlier versions shelled out to the AOM `inspect` tool, which dumped ~300 MB
> of JSON per clip to disk and re-parsed it. The in-memory dav1d path produces
> bit-identical motion vectors and reference maps while being roughly an order
> of magnitude faster end-to-end (see `test/validate_dav1d_vs_json.py`).

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [meson](https://mesonbuild.com/) + [ninja](https://ninja-build.org/) and a C
  compiler (for building dav1d); `nasm`/`yasm` recommended for SIMD on x86

## Installation

```bash
# Clone the repository
git clone https://github.com/sigmedia/AV1-Optical-Flow.git
cd AV1-Optical-Flow

# Run the setup script (installs Python deps via uv + builds patched dav1d)
bash setup.sh
```

The setup script will:
- Run `uv sync` to create a virtual environment and install all dependencies
  from `pyproject.toml`
- Clone [dav1d](https://code.videolan.org/videolan/dav1d) at the pinned commit,
  apply `patches/dav1d-inspection.patch`, and build it with the inspection
  callback enabled (`-Denable_inspection=true`)
- Install pre-commit hooks

If you don't have `uv` installed yet:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Usage

The input must be an **IVF-wrapped AV1** file.

```bash
uv run python main.py \
    --input_file path/to/video.ivf \
    --output_directory path/to/output/
```

### Options

| Flag | Description |
|---|---|
| `--input_file` | Path to the input AV1 `.ivf` file. |
| `--output_directory` | Directory where `.flo5` flow files are written. |
| `--linear_interpolation` | Normalise motion vectors by temporal distance to the reference frame. |
| `--upscale_function` | Upscale the motion field to frame resolution. Choices: `bicubic`, `nearest`, `bilinear`, `area`, `lanczos`. |
| `--bidirectional_filling` | Fill zero-motion intra blocks using the motion from the opposite direction. |
| `--threads` | Number of dav1d decoder threads. `0` (default) uses all logical cores. |
| `--logger_level` | Logging verbosity. Choices: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Default: `INFO`. |
| `--version` | Print version information and exit. |

### Example

Extract motion vectors with linear interpolation and bicubic upscaling:

```bash
uv run python main.py \
    --input_file input.ivf \
    --output_directory ./flows/ \
    --linear_interpolation \
    --upscale_function bicubic \
    --bidirectional_filling
```

This produces two files per frame in the output directory:

- `motion_backward_<N>.flo5` — backward motion field (current frame to past reference)
- `motion_forward_<N>.flo5` — forward motion field (current frame to future reference)

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run linter
uv run ruff check .

# Run type checker
uv run pyright

# Run pre-commit on all files
uv run pre-commit run --all-files
```

## Project Structure

```
AV1-Optical-Flow/
├── main.py                          # Entry point: orchestrates the full pipeline
├── pyproject.toml                   # Project metadata and dependencies (uv)
├── setup.sh                         # Builds patched dav1d and installs deps via uv
├── patches/
│   └── dav1d-inspection.patch       # dav1d per-frame block-metadata callback
├── src/
│   ├── av1of_inspect_shim.c         # C fast path: GIL-free per-frame array build
│   └── modules/
│       ├── dav1d_inspect.py         # In-memory metadata extraction (ctypes → dav1d)
│       ├── json_processing.py       # Post-processes motion vectors / reference maps
│       ├── flow_io.py               # Read/write optical flow in multiple formats
│       ├── utils.py                 # Upscaling, bidirectional filling, IVF validation
│       └── logger.py                # Logging configuration
├── test/
│   ├── 0018.ivf                     # Sample AV1 clip
│   └── validate_dav1d_vs_json.py    # Correctness + speed vs the AOM JSON reference
├── assets/
│   └── extract_motion.mp4          # Demo video
```

## How It Works

### Motion Vector Extraction

AV1 stores motion vectors at block granularity (down to 4x4 pixels). Each block
references one or two previously decoded frames and carries a 2D motion vector
per reference. The dav1d patch (`patches/dav1d-inspection.patch`) adds an
`inspect_cb` callback to `Dav1dSettings`; for every decoded frame it harvests
the decoder's internal 4x4 spatial block grid (`refmvs_block`) and hands it to
Python. `src/modules/dav1d_inspect.py` wraps libdav1d via `ctypes` and exposes
`iter_frames()`, yielding per frame:

- `motion_vectors` — `(H/4, W/4, 4)` int16, two MVs (backward + forward) in 1/8-pel
- `reference_map` — `(H/4, W/4, 2)` int16 reference indices
- `block_map` — `(H/4, W/4)` uint8 block sizes (AOM `BLOCK_*` ordering)

plus the per-frame order hint and reference order hints.

For throughput, a small C shim (`src/av1of_inspect_shim.c`, built into
`libav1of_inspect`) decodes the whole file in a single call and performs the
array construction (INVALID_MV normalisation, channel reordering, reference
split, block-size remap) in C on dav1d's worker threads — **without holding the
Python GIL**. This lets the multi-threaded decode scale to the decoder's own
limit instead of being pinned near single-thread speed by per-frame Python work.
If the shim is not built, `dav1d_inspect.py` transparently falls back to a pure
`ctypes` callback path (correct, but GIL-bound).

### Order Hints

AV1 identifies reference frames by *type* (LAST, GOLDEN, BWDREF, etc.), not by
frame number. dav1d already resolves each frame's `frame_offset` (order hint)
and per-reference order hints (`refpoc`) during decoding, so these are returned
alongside the block metadata — no separate bitstream parse is needed. The
pipeline unwraps AV1's cyclic order hints (0–127) into absolute frame numbers
for temporal normalisation.

### Post-Processing

| Step | Description |
|---|---|
| **Linear interpolation** | Divides each motion vector by the temporal distance to its reference frame, normalising to a per-frame displacement. |
| **Bidirectional filling** | Copies the negated motion vector from the opposite direction into blocks that have zero motion (intra blocks). |
| **Upscaling** | Resizes the block-level motion field to full frame resolution using OpenCV interpolation. |

## License

This project is licensed under the [GNU Affero General Public License v3.0](LICENSE).

```
Copyright (C) 2026  Sigmedia.tv / Julien Zouein (zoueinj@tcd.ie)
```

## Citation
```bibtex
@inproceedings{inproceedings,
author = {Zouein, Julien and Vibhoothi, Vibhoothi and Kokaram, Anil},
year = {2025},
month = {12},
pages = {1-5},
title = {AV1 Motion Vector Fidelity and Application for Efficient Optical Flow},
doi = {10.1109/PCS65673.2025.11417638}
}
```
