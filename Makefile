run-tests:
	pipenv run pytest test_pipenv.py
run-tox:
	pipenv run tox
init:
	pip install pipenv
	pipenv install --dev
clean:
	find . -name '*.pyc' -delete
	rm -rf .tox
	rm -rf .venv
