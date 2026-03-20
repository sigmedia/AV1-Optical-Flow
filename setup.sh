#!/bin/bash
set -e

# Install Python dependencies via uv
uv sync

# Build AOM with inspection API
cd src/third_parties

git clone https://aomedia.googlesource.com/aom
mkdir aom_build
cd aom_build
cmake ../aom/ -DCONFIG_TUNE_VMAF=1 -DENABLE_CCACHE=1 -DCONFIG_INSPECTION=1
make -j"$(nproc)"

cd ../../..

# Install pre-commit hooks
uv run pre-commit install
