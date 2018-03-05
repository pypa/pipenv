#!/usr/bin/env bash

set -e

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR


if [[ ! -z "$TEST_SUITE" ]]; then
	TEST_SUITE=""
fi

if [[ ! -z "$NOT_CI" ]]; then
	echo "Creating RAM disk…"

	RAM_DISK="/media/ramdisk"
	export RAM_DISK

	sudo mkdir -p "$RAM_DISK"
	sudo mount -t tmpfs -o size=4048M tmpfs "$RAM_DISK"
fi


pytest -v -n 8 tests -m "$TEST_SUITE" --tap-stream