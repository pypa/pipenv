.PHONY: docs

run-tests:
	pipenv run pytest tests
init:
	python setup.py install
	pipenv install --dev
docs:
	cd docs && make html
kenneth:
	pipenv run pytest -n 8 tests/test_pipenv.py
