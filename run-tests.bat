pip install -e . --upgrade --upgrade-strategy=only-if-needed
pipenv install --dev

pipenv run pytest -v tests --tap-stream | tee results.tap