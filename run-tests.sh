#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -eo pipefail

# Set the PYPI vendor URL for pytest-pypi.
export PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"

if [[ ! -z "$TEST_SUITE" ]]; then
    echo "Using TEST_SUITE=$TEST_SUITE"
fi

# First, try MacOS…
echo "Clearing Caches…"
if [[ $(python -c "import sys; print(sys.platform)") == "darwin" ]]; then
    CACHE_ROOT=~/Library/Caches
# Otherwise, assume Linux…
else
    CACHE_ROOT=~/.cache
fi
rm -fr ${CACHE_ROOT}/pip
rm -fr ${CACHE_ROOT}/pipenv

# If the lockfile hasn't changed, skip installs.
echo "Installing Pipenv…"
pip install -e "$(pwd)" --upgrade-strategy=only-if-needed

echo "Installing dependencies…"
PIPENV_PYTHON=2.7 pipenv run pip install -e . --upgrade
PIPENV_PYTHON=3.6 pipenv run pip install -e . --upgrade
PIPENV_PYTHON=2.7 pipenv install --dev
PIPENV_PYTHON=3.6 pipenv install --dev

echo "Running tests…"
PIPENV_PYTHON=2.7 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"
PIPENV_PYTHON=3.6 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"

# Cleanup junk.
rm -fr .venv
