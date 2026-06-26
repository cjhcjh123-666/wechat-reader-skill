#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
cache_dir="${CLANG_MODULE_CACHE_PATH:-$script_dir/.swift-cache}"
mkdir -p "$cache_dir"
CLANG_MODULE_CACHE_PATH="$cache_dir" swiftc "$script_dir/ocr_vision.swift" -o "$script_dir/ocr_vision"
echo "$script_dir/ocr_vision"
