#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -e

PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR


if [[ ! -z "$TEST_SUITE" ]]; then
	echo "Using TEST_SUITE=$TEST_SUITE"
fi

if [[ ! -z "$CI" ]]; then
	# If running in CI environment…
	echo "Using RAM disk…"

	RAM_DISK="/opt/ramdisk"
	export RAM_DISK

	echo "Installing Pipenv…"

	pip install -e . --upgrade --upgrade-strategy=only-if-needed
	pipenv install --deploy --system --dev
	TAP_OUPUT=1

else
	# Otherwise, assume MacOS…
	# TODO: Improve this for Linux users (e.g. Nick).
	echo "Using RAM disk (assuming MacOS)…"
	if [[ ! -d "/Volumes/RamDisk" ]]; then
		diskutil erasevolume HFS+ 'RAMDisk' $(hdiutil attach -nomount ram://8388608)
	fi

	RAM_DISK="/Volumes/RAMDisk"
	export RAM_DISK

	if [[ ! -d "$RAM_DISK/.venv" ]]; then
		echo "Creating a new venv on RAM Disk…"
		python3 -m venv "$RAM_DISK/.venv"
	fi

	# If the lockfile hasn't changed, skip installs.
	if [[ $(openssl dgst -sha256 Pipfile.lock) != $(cat "$RAM_DISK/.venv/Pipfile.lock.sha256") ]]; then
		echo "Instaling Pipenv…"
		"$RAM_DISK/.venv/bin/pip" install -e "$(pwd)" --upgrade-strategy=only-if-needed

		"$RAM_DISK/.venv/bin/pipenv" install --dev

		# Hash the lockfile, to skip intalls next time.
		openssl dgst -sha256 Pipfile.lock > "$RAM_DISK/.venv/Pipfile.lock.sha256"
	fi


fi

if [[ "$TAP_OUTPUT" ]]; then
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\" --tap-stream | tee report.tap"
	"$RAM_DISK/.venv/bin/pipenv" run time pytest -v -n auto tests -m "$TEST_SUITE"  --tap-stream | tee report.tap
else
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\""
	"$RAM_DISK/.venv/bin/pipenv" run time pytest -v -n auto tests -m "$TEST_SUITE"
fi