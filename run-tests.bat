virtualenv .venv
.venv\Scripts\pip install -e . --upgrade --upgrade-strategy=only-if-needed
.venv\Scripts\pipenv install --dev


.venv\Scripts\pipenv run -n auto pytest -v tests --tap-stream | tee results.tap