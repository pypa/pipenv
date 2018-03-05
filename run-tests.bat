pip install -e . --upgrade --upgrade-strategy=only-if-needed
pipenv install --dev

pipenv run pytest -v -n auto tests --tap-stream