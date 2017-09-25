.PHONY: docs

run-tests:
	pipenv run pytest tests
init:
	python setup.py install
	pipenv install --dev
docs:
	cd docs && make html
man:
	cd docs && make man
	mv docs/_build/man/pipenv.1 pipenv/pipenv.1
