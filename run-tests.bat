virtualenv .venv
.venv\Scripts\pip install -e . --upgrade --upgrade-strategy=only-if-needed
.venv\Scripts\pipenv install --dev


.venv\Scripts\pipenv run pytest -n auto --boxed -v tests --tap-stream | tee results.tap