.PHONY: docs

define PRINT_HELP_PYSCRIPT
import re, sys

for line in sys.stdin:
	match = re.match(r'^([a-zA-Z_-]+):.*?## (.*)$$', line)
	if match:
		target, help = match.groups()
		print("%-20s %s" % (target, help))
endef
export PRINT_HELP_PYSCRIPT

help: ## display this message
	@python -c "$$PRINT_HELP_PYSCRIPT" < $(MAKEFILE_LIST)

run-tests: ## run tests
	pipenv run pytest tests

init: ## initialize project
	pip install -U setuptools
	python setup.py install
	pipenv install --dev

docs: ## generate docs
	cd docs && make html

man: ## generate manpages
	cd docs && make man
	mv docs/_build/man/pipenv.1 pipenv/pipenv.1

publish: ## publish project
	python setup.py sdist bdist_wheel upload

upload: ## upload project
	@echo "\033[1mRemoving previous builds…\033[0m"
	rm -rf ./dist
	@echo "\033[1mBuilding Source distribution…\033[0m"
	python setup.py sdist
	@echo "\033[1mUploading the package to PyPi via Twine…\033[0m"
	twine upload dist/*
	@echo "\033[1mPushing git tags…\033[0m"
	git tag v`python -m pipenv.__version__`
	git push --tags
