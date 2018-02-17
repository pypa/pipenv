.PHONY: help ## Print this help
help:
	@grep -E '^\.PHONY: [a-zA-Z_-]+ .*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = "(: |##)"}; {printf "\033[36m%-30s\033[0m %s\n", $$2, $$3}'

.PHONY: run-tests ## Run unit tests
run-tests:
	pipenv run pytest tests

.PHONY: init ## Initialize pipenv for development
init:
	python setup.py develop
	pipenv install --dev

.PHONY: docs ## Generate documentation
docs:
	cd docs && make html

.PHONY: ## Generate man documentation
man:
	cd docs && make man
	mv docs/_build/man/pipenv.1 pipenv/pipenv.1
