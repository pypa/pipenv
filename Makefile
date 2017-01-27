run-tests:
	pipenv run pytest test_pipenv.py
run-tox:
	pipenv run tox
init:
	pip install pipenv
	pipenv install --dev
clean:
# http://stackoverflow.com/questions/28991015/python3-project-remove-pycache-folders-and-pyc-files
	find . -regex "\(.*__pycache__.*\|*.py[co]\)" -delete
	rm -rf .tox
	rm -rf .venv
