.PHONY: docs

run-tests:
	pipenv run pytest tests
init:
	python setup.py install
	pipenv install --dev
docs:
	cd docs && make html
