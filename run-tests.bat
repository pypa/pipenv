
pip install -e .[test] --upgrade --upgrade-strategy=only-if-needed
pipenv install --dev
git submodule sync && git submodule update --init --recursive
cmd /c start pipenv run pypi-server run -v --host=0.0.0.0 --port=8080 --hash-algo=sha256 --disable-fallback ./tests/pypi/ ./tests/fixtures
pipenv run pytest -n auto -v tests
