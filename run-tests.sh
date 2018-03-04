#!/usr/bin/env bash

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR

pytest -n 8 tests -m "$TEST_SUITE"