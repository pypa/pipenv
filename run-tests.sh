#!/usr/bin/env bash

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR

pytest -n auto tests/test_pipenv.py -m "$TEST_SUITE"