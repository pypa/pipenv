tests:
	pipenv run pytest test_pipenv.py
init:
	pip install pipenv
	pipenv install --dev
