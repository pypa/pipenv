#!/usr/bin/env bash

set -e

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR


if [[ ! -z "$TEST_SUITE" ]]; then
	TEST_SUITE=""
fi

if [[ ! -z "$CI" ]]; then
	echo "Creating RAM disk…"

	RAM_DISK="/media/ramdisk"
	export RAM_DISK

	sudo mkdir -p "$RAM_DISK"
	sudo mount -t tmpfs -o size=1M tmpfs "$RAM_DISK"
fi


pytest -n 4 tests -m "$TEST_SUITE"