#!/usr/bin/env bash

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR

if [[ ! "$TEST_SUITE" ]]; then
	TEST_SUITE = ""
fi

pytest -n 8 tests -m "$TEST_SUITE"