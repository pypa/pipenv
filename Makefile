get_venv_dir:=$(shell mktemp -d 2>/dev/null || mktemp -d -t 'tmpvenv')
venv_dir := $(get_venv_dir)/pipenv_venv
venv_file := $(CURDIR)/.test_venv
get_venv_path =$(file < $(venv_file))

format:
	black pipenv/*.py
test:
	docker-compose up

.PHONY: ramdisk
ramdisk:
	sudo mkdir -p /mnt/ramdisk
	sudo mount -t tmpfs -o size=2g tmpfs /mnt/ramdisk
	sudo chown -R ${USER}:${USER} /mnt/ramdisk

.PHONY: ramdisk-virtualenv
ramdisk-virtualenv: ramdisk
	[ ! -e "/mnt/ramdisk/.venv/bin/activate" ] && \
		python -m virtualenv /mnt/ramdisk/.venv
	@echo "/mnt/ramdisk/.venv" >> $(venv_file)

.PHONY: virtualenv
virtualenv:
	[ ! -e $(venv_dir) ] && rm -rf $(venv_file) && python -m virtualenv $(venv_dir)
	@echo $(venv_dir) >> $(venv_file)

.PHONY: test-install
test-install: virtualenv
	. $(get_venv_path)/bin/activate && \
		python -m pip install --upgrade pip virtualenv -e .[tests,dev] && \
		pipenv install --dev

.PHONY: submodules
submodules:
	git submodule sync
	git submodule update --init --recursive

.PHONY: tests
tests: virtualenv submodules test-install
	. $(get_venv_path)/bin/activate && \
		pipenv run pytest -ra -vvv --full-trace --tb=long

.PHONY: test-specific
test-specific: submodules virtualenv test-install
	. $(get_venv_path)/bin/activate && pipenv run pytest -ra -k '$(tests)'

.PHONY: retest
retest: virtualenv submodules test-install
	. $(get_venv_path)/bin/activate && pipenv run pytest -ra -k 'test_check_unused or test_install_editable_git_tag or test_get_vcs_refs or test_skip_requirements_when_pipfile or test_editable_vcs_install or test_basic_vcs_install or test_git_vcs_install or test_ssh_vcs_install or test_vcs_can_use_markers' -vvv --full-trace --tb=long
