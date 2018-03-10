#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -e

# Set the PYPI vendor URL for pytest-pypi.
PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
export PYPI_VENDOR_DIR


if [[ ! -z "$TEST_SUITE" ]]; then
	echo "Using TEST_SUITE=$TEST_SUITE"
fi

# If running in CI environment…
if [[ ! -z "$CI" ]]; then
	echo "Running in a CI environment…"

	echo "Using RAM disk…"
	RAM_DISK="/opt/ramdisk"
	export RAM_DISK

	# Use tap output for tests.
	TAP_OUTPUT="1"
	export TAP_OUTPUT

	# Check for a checksum of the lockfile on the RAM Disk.
	if [[ -f "$RAM_DISK/Pipfile.lock.sha256-nevermind" ]]; then

		# If it's not the same, re-install.
		if [[ $(openssl dgst -sha256 Pipfile.lock) != $(cat "$RAM_DISK/Pipfile.lock.sha256") ]]; then
			INSTALL_PIPENV=1
			echo "Installing Pipenv…"
		fi
	else
		# If the checksum doesn't exist, re-install.
		INSTALL_PIPENV=1
	fi

	# Install Pipenv…
	if [[ "$INSTALL_PIPENV" ]]; then
		pip install -e "$(pwd)" --upgrade
		pipenv install --deploy --system --dev

		openssl dgst -sha256 Pipfile.lock > "$RAM_DISK/Pipfile.lock.sha256"
	fi


# Otherwise, we're on a development machine.
else
	# First, try MacOS…
	if [[ $(python -c "import sys; print(sys.platform)") == "darwin" ]]; then
		echo "Using RAM disk (assuming MacOS)…"

		RAM_DISK="/Volumes/RAMDisk"
		export RAM_DISK

		if [[ ! -d "$RAM_DISK" ]]; then
			echo "Creating RAM Disk ($RAM_DISK)…"
			diskutil erasevolume HFS+ 'RAMDisk' $(hdiutil attach -nomount ram://8388608)
		fi

	# Otherwise, assume Linux…
	else
		echo "Using RAM disk (assuming Linux)…"

		RAM_DISK="/media/ramdisk"
		export RAM_DISK

		if [[ ! -d "$RAM_DISK" ]]; then
			echo "Creating RAM Disk ($RAM_DISK)…"
			sudo mkdir -p "$RAM_DISK"
			sudo mount -t tmpfs -o size=4096M tmpfs "$RAM_DISK"
		fi
	fi

	# If the virtualenv doesn't exist, create it.
	if [[ ! -d "$RAM_DISK/.venv" ]]; then
		echo "Creating a new venv on RAM Disk…"
		virtualenv "$RAM_DISK/.venv"
	fi

	# If the lockfile hasn't changed, skip installs.
	if [[ $(openssl dgst -sha256 Pipfile.lock) != $(cat "$RAM_DISK/.venv/Pipfile.lock.sha256") ]]; then
		echo "Instaling Pipenv…"
		"$RAM_DISK/.venv/bin/pip" install -e "$(pwd)" --upgrade-strategy=only-if-needed

		echo "Installing dependencies…"
		"$RAM_DISK/.venv/bin/pipenv" install --dev

		# Hash the lockfile, to skip intalls next time.
		openssl dgst -sha256 Pipfile.lock > "$RAM_DISK/.venv/Pipfile.lock.sha256"
	fi


fi

# Use tap output if in a CI environment, otherwise just run the tests.
if [[ "$TAP_OUTPUT" ]]; then
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\" --tap-stream | tee report-$PYTHON.tap"
	pipenv run time pytest -v -n auto tests -m "$TEST_SUITE"  --tap-stream | tee report.tap
else
	echo "$ pipenv run time pytest -v -n auto tests -m \"$TEST_SUITE\""
	"$RAM_DISK/.venv/bin/pipenv" run time pytest -v -n auto tests -m "$TEST_SUITE"
fi