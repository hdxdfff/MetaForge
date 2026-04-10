#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

PACKAGES=(
  build-essential
  gcc
  g++
  gcc-multilib
  binutils
  make
  cmake
  nasm
  qemu-system-x86
  python3
  python3-pip
  python3-venv
  git
  curl
  unzip
  pkg-config
)

echo "[setup] updating apt indexes"
$SUDO apt-get update

echo "[setup] upgrading base packages"
$SUDO apt-get upgrade -y

echo "[setup] installing packages: ${PACKAGES[*]}"
$SUDO apt-get install -y "${PACKAGES[@]}"

echo "[setup] package versions"
python3 --version || true
gcc --version | head -n 1 || true
nasm -v || true
qemu-system-i386 --version | head -n 1 || true
git --version || true

echo "[setup] done"