#!/usr/bin/env bash

# NOTE: set TEST_SUITE to be markers you want to run.

set -eo pipefail

export PYTHONIOENCODING="utf-8"
export LANG=C.UTF-8
export PIP_PROCESS_DEPENDENCY_LINKS="1"
# Let's use a temporary cache directory
export PIPENV_CACHE_DIR=`mktemp -d 2>/dev/null || mktemp -d -t 'pipenv_cache'`

prefix() {
	sed "s/^/   $1:    /"
}

if [[ ! -z "$TEST_SUITE" ]]; then
	echo "Using TEST_SUITE=$TEST_SUITE"
fi

HOME=$(readlink -f ~/)
if [[ -z "$HOME" ]]; then
    if [[ "$USER" == "root" ]]; then
        HOME="/root"
    fi
fi
if [[ ! -z "$HOME" ]]; then
    export PATH="${HOME}/.local/bin:${PATH}"
fi
pip install certifi
export GIT_SSL_CAINFO=$(python -m certifi)
echo "Path: $PATH"
echo "Installing Pipenv…"
python -m pip install --upgrade -e "$(pwd)" setuptools wheel pip
VENV_CMD="python -m pipenv --venv"
RM_CMD="pipenv --rm"
echo "$ PIPENV_PYTHON=2.7 $VENV_CMD && PIPENV_PYTHON=2.7 $RM_CMD"
echo "$ PIPENV_PYTHON=3.7 $VENV_CMD && PIPENV_PYTHON=3.7 $RM_CMD"
{ PIPENV_PYTHON=2.7 $VENV_CMD && PIPENV_PYTHON=2.7 $RM_CMD ; PIPENV_PYTHON=3.7 $VENV_CMD && PIPENV_PYTHON=3.7 $RM_CMD ; }

echo "Installing dependencies…"
INSTALL_CMD="python -m pipenv install --deploy --dev"
echo "$ PIPENV_PYTHON=2.7 $INSTALL_CMD"
echo "$ PIPENV_PYTHON=3.7 $INSTALL_CMD"

{ ( PIPENV_PYTHON=2.7 $INSTALL_CMD & ); PIPENV_PYTHON=3.7 $INSTALL_CMD ; }
echo "$ git submodule sync && git submodule update --init --recursive"

git submodule sync && git submodule update --init --recursive

echo "$ pipenv run time pytest"
PIPENV_PYTHON=2.7 python -m pipenv run time pytest
PIPENV_PYTHON=3.7 python -m pipenv run time pytest
