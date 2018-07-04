#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -eo pipefail

# Set the PYPI vendor URL for pytest-pypi.
PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR
export PYTHONIOENCODING="utf-8"
export LANG=C.UTF-8

prefix() {
	sed "s/^/   $1:    /"
}

if [[ ! -z "$TEST_SUITE" ]]; then
	echo "Using TEST_SUITE=$TEST_SUITE"
fi

export PATH="$HOME/.local/bin:$PATH"
# pip uninstall -y pipenv
echo "Installing Pipenv…"
pip install -e "$(pwd)" --upgrade
pipenv install --deploy --dev

# Otherwise, we're on a development machine.
# First, try MacOS…
if [[ $(python -c "import sys; print(sys.platform)") == "darwin" ]]; then

	echo "Clearing Caches…"
	rm -fr ~/Library/Caches/pip
	rm -fr ~/Library/Caches/pipenv

# Otherwise, assume Linux…
else
	echo "Clearing Caches…"
	rm -fr ~/.cache/pip
	rm -fr ~/.cache/pipenv
fi

echo "Installing dependencies…"
PIPENV_PYTHON=2.7 pipenv run pip install -e . --upgrade
PIPENV_PYTHON=3.7 pipenv run pip install -e . --upgrade
PIPENV_PYTHON=2.7 pipenv install --dev
PIPENV_PYTHON=3.7 pipenv install --dev

echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\""
# PIPENV_PYTHON=2.7 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE" | prefix 2.7 &
# PIPENV_PYTHON=3.6 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE" | prefix 3.6
# Better to run them sequentially.
PIPENV_PYTHON=2.7 pipenv run time pytest
PIPENV_PYTHON=3.7 pipenv run time pytest

# test revendoring
pip3 install --upgrade invoke requests parver
python3 -m invoke vendoring.update
# Cleanup junk.
rm -fr .venv
