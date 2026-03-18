#!/bin/bash

python3 -m pip install -r requirements.txt

cd src/third_parties

# Installing AOM dependencies

git clone https://aomedia.googlesource.com/aom
mkdir aom_build
cd aom_build
cmake ../aom/ -DCONFIG_TUNE_VMAF=1 -DENABLE_CCACHE=1 -DCONFIG_INSPECTION=1
make -j8

cd ..

# Installing AV1Parser dependencies

git clone git@github.com:yohhoy/av1parser.git