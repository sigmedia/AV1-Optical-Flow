# AV1-Optical-Flow

Extract and pre-process motion vectors from AV1 bitstreams for fast and cheap optical flow estimation.

https://github.com/user-attachments/assets/extract_motion.mp4

## Overview

AV1-Optical-Flow extracts the motion vectors that the AV1 encoder already
computes during compression and converts them into standard optical flow fields
(`.flo5` format).  Because the motion information is a free by-product of
video encoding, this approach is orders of magnitude faster than running a
dedicated optical flow network, making it suitable for real-time or
large-scale video analysis pipelines.

The pipeline:

1. **Decodes** the AV1 bitstream with the AOM `inspect` tool, which dumps
   per-frame metadata (motion vectors, reference maps, block modes) to JSON.
2. **Parses** the raw bitstream to extract reference frame order hints,
   converting AV1's internal reference indices into actual frame numbers.
3. **Post-processes** the motion vectors with optional linear interpolation,
   upscaling, and bidirectional filling.
4. **Writes** the result as `.flo5` (HDF5-compressed) flow files.

## Requirements

- Python 3.10+
- CMake and a C compiler (for building AOM)
- The dependencies listed in `requirements.txt`

## Installation

```bash
# Clone the repository
git clone https://github.com/<your-username>/AV1-Optical-Flow.git
cd AV1-Optical-Flow

# Run the setup script (installs Python deps + builds AOM from source)
bash setup.sh
```

The setup script will:
- Install all Python dependencies from `requirements.txt`
- Clone and build [AOM](https://aomedia.googlesource.com/aom) with the
  inspection API enabled (`CONFIG_INSPECTION=1`)

## Usage

The input must be an **IVF-wrapped AV1** file.

```bash
python main.py \
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
| `--logger_level` | Logging verbosity. Choices: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. Default: `INFO`. |
| `--version` | Print version information and exit. |

### Example

Extract motion vectors with linear interpolation and bicubic upscaling:

```bash
python main.py \
    --input_file input.ivf \
    --output_directory ./flows/ \
    --linear_interpolation \
    --upscale_function bicubic \
    --bidirectional_filling
```

This produces two files per frame in the output directory:

- `motion_backward_<N>.flo5` — backward motion field (current frame to past reference)
- `motion_forward_<N>.flo5` — forward motion field (current frame to future reference)

## Project Structure

```
AV1-Optical-Flow/
├── main.py                          # Entry point: orchestrates the full pipeline
├── setup.sh                         # Builds AOM and installs Python dependencies
├── requirements.txt                 # Python dependencies
├── src/
│   └── modules/
│       ├── av1_parser.py            # Pure-Python AV1 bitstream parser (order hints)
│       ├── json_processing.py       # Processes AOM inspect JSON (motion vectors)
│       ├── flow_io.py               # Read/write optical flow in multiple formats
│       ├── utils.py                 # Upscaling, bidirectional filling, IVF validation
│       └── logger.py                # Logging configuration
├── doc/
│   └── av1_parser.md               # Technical documentation for the AV1 parser
├── assets/
│   └── Extract Motion.mp4          # Demo video
└── test/                            # Tests
```

## How It Works

### Motion Vector Extraction

AV1 stores motion vectors at block granularity (typically 4x4 pixels).  Each
block references one or two previously decoded frames and carries a 2D motion
vector per reference.  The AOM `inspect` tool exposes these as a JSON array
of shape `(H/4, W/4, 4)` — two components each for the backward and forward
references.

### Order Hint Parsing

AV1 identifies reference frames by *type* (LAST, GOLDEN, BWDREF, etc.), not by
frame number.  To convert these into actual frame numbers — needed for temporal
normalisation — the pipeline includes a pure-Python AV1 bitstream parser
(`av1_parser.py`) that reads the IVF container and extracts the `order_hint`
and `ref_frame_idx` fields from each frame header, tracking the 8-slot
reference buffer across the entire sequence.

See [`doc/av1_parser.md`](doc/av1_parser.md) for a detailed technical
explanation.

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
