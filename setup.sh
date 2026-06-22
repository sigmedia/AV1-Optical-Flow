#!/bin/bash
set -e

# Absolute path to the repository root (so the script is location-independent).
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# dav1d release the inspection patch is built against.
DAV1D_REPO="https://code.videolan.org/videolan/dav1d.git"
DAV1D_COMMIT="14c73c7db38eebfd3202146b76a1ad4df90dd3a2"  # 1.5.3-58-g14c73c7d

# Install Python dependencies via uv
uv sync

mkdir -p src/third_parties
cd src/third_parties

# Build dav1d with the in-memory inspection callback.
# We clone the pinned commit and apply the AV1-Optical-Flow patch, which adds a
# per-frame block-metadata callback (gated by -Denable_inspection=true).
if [ ! -d dav1d ]; then
  git clone "$DAV1D_REPO" dav1d
  cd dav1d
  git checkout "$DAV1D_COMMIT"
  git apply "$ROOT/patches/dav1d-inspection.patch"
else
  cd dav1d
fi

meson setup build --buildtype release -Denable_inspection=true \
  || meson configure build -Denable_inspection=true
ninja -C build

cd "$ROOT/src/third_parties"

# Build the in-memory inspection shim: it transforms each frame's block metadata
# into NumPy-ready buffers in C (GIL-free), letting the multi-threaded decode
# scale. The shim is linked directly against OUR patched libdav1d with an rpath
# (relative to the shim's own location), so it binds to that specific library
# and is NOT interposed by any other libdav1d already loaded in the process
# (e.g. the unpatched copy that OpenCV/cv2 bundles).
SHIM_CC_FLAGS="-O3 -shared -fPIC -I dav1d/include"
if [ "$(uname)" = "Darwin" ]; then
  cc $SHIM_CC_FLAGS -o libav1of_inspect.dylib "$ROOT/src/av1of_inspect_shim.c" \
    dav1d/build/src/libdav1d.7.dylib \
    -Wl,-rpath,@loader_path/dav1d/build/src
else
  cc $SHIM_CC_FLAGS -o libav1of_inspect.so "$ROOT/src/av1of_inspect_shim.c" \
    -L dav1d/build/src -ldav1d \
    -Wl,-rpath,'$ORIGIN/dav1d/build/src'
fi

cd "$ROOT"

# Install pre-commit hooks
uv run pre-commit install
