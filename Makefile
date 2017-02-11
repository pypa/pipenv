.PHONY: docs

run-tests:
	pipenv run pytest tests
init:
	pip install pipenv
	pipenv install --dev
docs:
	cd docs && make html
