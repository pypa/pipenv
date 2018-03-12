#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -e

# Set the PYPI vendor URL for pytest-pypi.
PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR

prefix() {
  sed "s/^/   $1:    /"
}

if [[ ! -z "$TEST_SUITE" ]]; then
	echo "Using TEST_SUITE=$TEST_SUITE"
fi

# If running in CI environment…
if [[ ! -z "$CI" ]]; then
	echo "Running in a CI environment…"

	# Use tap output for tests.
	TAP_OUTPUT="1"
	export TAP_OUTPUT

	echo "Installing Pipenv…"


	pip install -e "$(pwd)" --upgrade
	pipenv install --deploy --system --dev

# Otherwise, we're on a development machine.
else
	# First, try MacOS…
	if [[ $(python -c "import sys; print(sys.platform)") == "darwin" ]]; then

		echo "Clearing Caches…"
		rm -fr ~/Library/Caches/pip
		rm -fr ~/Libary/Caches/pipenv

	# Otherwise, assume Linux…
	else
		echo "Clearing Caches…"
		rm -fr ~/.cache/pip
		rm -fr ~/.cache/pipenv
	fi

	# If the lockfile hasn't changed, skip installs.

	echo "Instaling Pipenv…"
	pip install -e "$(pwd)" --upgrade-strategy=only-if-needed

	echo "Installing dependencies…"
	PIPENV_PYTHON=2.7 pipenv run pip install -e . --upgrade
	PIPENV_PYTHON=3.6 pipenv run pip install -e . --upgrade
	PIPENV_PYTHON=2.7 pipenv install --dev
	PIPENV_PYTHON=3.6 pipenv install --dev

fi

# Use tap output if in a CI environment, otherwise just run the tests.
if [[ "$TAP_OUTPUT" ]]; then
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\" --tap-stream | tee report-$PYTHON.tap"
	pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"  --tap-stream | tee report.tap
else
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\""
	# PIPENV_PYTHON=2.7 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE" | prefix 2.7 &
	# PIPENV_PYTHON=3.6 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE" | prefix 3.6
	# Better to run them sequentially.
	PIPENV_PYTHON=2.7 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"
	PIPENV_PYTHON=3.6 pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"
	# Cleanup junk.
	rm -fr .venv
fi