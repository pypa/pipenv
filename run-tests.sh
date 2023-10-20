#!/usr/bin/env bash

# Tested on debian and alpine
# You will need to install some dependencies yourself.

set -eo pipefail

export PYTHONIOENCODING="utf-8"
export LANG=C.UTF-8

# Let's use a temporary cache directory
export PIPENV_CACHE_DIR=`mktemp -d 2>/dev/null || mktemp -d -t 'pipenv_cache'`

# on some Linux OS python is python3
PYTHON=${PYTHON:-"python"}
PIPENV_PYTHON="${PIPENV_PYTHON:-3.8}"

PIP_CALL="${PIP_CALL:-${PYTHON} -m pip install --user}"

HOME=$(readlink -f ~/)

if [[ -z "$HOME" ]]; then
    if [[ "$USER" == "root" ]]; then
        HOME="/root"
    fi
fi

if [[ ! -z "$HOME" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
fi

# This installs the dependencies for pipenv
${PIP_CALL} --upgrade pip setuptools wheel virtualenv --upgrade-strategy=eager

VENV_CMD="${PYTHON} -m pipenv --venv"
RM_CMD="pipenv --rm"

echo "$ PIPENV_PYTHON=${PIPENV_PYTHON} $VENV_CMD && PIPENV_PYTHON=${PIPENV_PYTHON} $RM_CMD"

{ PIPENV_PYTHON="${PIPENV_PYTHON}" $VENV_CMD && PIPENV_PYTHON=${PIPENV_PYTHON} $RM_CMD ; }

echo "Installing dependencies..."

INSTALL_CMD="${PYTHON} -m pipenv install --deploy --dev"

echo "$ PIPENV_PYTHON=${PIPENV_PYTHON} $INSTALL_CMD"

PIPENV_PYTHON=${PIPENV_PYTHON} $INSTALL_CMD

echo "$ git submodule sync && git submodule update --init --recursive"

git submodule sync && git submodule update --init --recursive

echo "pipenv run pypi-server run -v --host=0.0.0.0 --port=8080 --hash-algo=sha256 --disable-fallback ./tests/pypi/ ./tests/fixtures &"

pipenv run pypi-server run -v --host=0.0.0.0 --port=8080 --hash-algo=sha256 --disable-fallback ./tests/pypi/ ./tests/fixtures &

echo "$pipenv run pytest -v -ra -n auto --cov-config pyproject.toml --fulltrace tests"

PIPENV_PYTHON=${PIPENV_PYTHON} ${PYTHON} -m pipenv run pytest -v -ra -n auto --cov-config pyproject.toml --fulltrace tests
