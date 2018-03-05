#!/usr/bin/env bash

set -e

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR


if [[ ! -z "$TEST_SUITE" ]]; then
	TEST_SUITE=""
fi

if [[ ! -z "$CI" ]]; then
	echo "Using RAM disk…"

	RAM_DISK="/opt/ramdisk"
	export RAM_DISK

	echo "Installing Pipenv…"
	pip install -e . --upgrade --upgrade-strategy=only-if-needed
	pipenv install --dev
fi


pipenv run pytest -v -n 8 tests -m "$TEST_SUITE" --tap-stream | tee results.tap