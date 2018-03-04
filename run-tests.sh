#!/usr/bin/env bash

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR

pytest -n 8 tests/test_pipenv.py -m "$TEST_SUITE"