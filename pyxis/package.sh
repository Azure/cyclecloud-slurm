#!/bin/bash
set -x

ENROOT_VERSION=3.5.0
PYXIS_VERSION=0.20.0

# Remove any previous .build directory and create a new one
rm -rf .build
mkdir -p .build/pyxis-artifacts

# https://github.com/NVIDIA/enroot/releases/download/v3.5.0/enroot-check_3.5.0_arm64.run
# 


for arch in x86_64 aarch64; do
    curl -fSsL -o .build/pyxis-artifacts/enroot-check_${ENROOT_VERSION}_${arch}.run https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-check_${ENROOT_VERSION}_${arch}.run
    curl -fSsL -o .build/pyxis-artifacts/enroot-${ENROOT_VERSION}-1.el8.${arch}.rpm https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-${ENROOT_VERSION}-1.el8.${arch}.rpm
    curl -fSsL -o .build/pyxis-artifacts/enroot+caps-${ENROOT_VERSION}-1.el8.${arch}.rpm https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot+caps-${ENROOT_VERSION}-1.el8.${arch}.rpm
done
for arch in amd64 arm64; do
    #curl -fSsL -o .build/pyxis-artifacts/enroot-check_${ENROOT_VERSION}_${arch}.run https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot-check_${ENROOT_VERSION}_${arch}.run
    curl -fSsL -o .build/pyxis-artifacts/enroot_${ENROOT_VERSION}-1_${arch}.deb https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot_${ENROOT_VERSION}-1_${arch}.deb
    curl -fSsL -o .build/pyxis-artifacts/enroot+caps_${ENROOT_VERSION}-1_${arch}.deb https://github.com/NVIDIA/enroot/releases/download/v${ENROOT_VERSION}/enroot+caps_${ENROOT_VERSION}-1_${arch}.deb
done

wget -q -O .build/pyxis-artifacts/pyxis-${PYXIS_VERSION}.tar.gz https://github.com/NVIDIA/pyxis/archive/refs/tags/v${PYXIS_VERSION}.tar.gz

tar -czvf pyxis-artifacts.tar.gz -C .build .