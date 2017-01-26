run-tests:
	pipenv run pytest test_pipenv.py
init:
	pip install pipenv
	pipenv install --dev
clean:
	find . -name '*.pyc' -delete
	rm -rf .tox
