virtualenv .venv
.venv\Scripts\pip install -e . --upgrade --upgrade-strategy=only-if-needed
.venv\Scripts\pipenv install --dev


.venv\Scripts\pipenv run pytest -v tests -m windows --tap-stream | tee results.tap
