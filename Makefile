get_venv_dir:=$(shell mktemp -d 2>/dev/null || mktemp -d -t 'tmpvenv')
venv_dir := $(get_venv_dir)/pipenv_venv
venv_file := $(CURDIR)/.test_venv
get_venv_path =$(file < $(venv_file))
# This is how we will build tag-specific wheels, e.g. py36 or py37
PY_VERSIONS:= 3.7 3.8 3.9 3.10
BACKSLASH = '\\'
# This is how we will build generic wheels, e.g. py2 or py3
INSTALL_TARGETS := $(addprefix install-py,$(PY_VERSIONS))
CLEAN_TARGETS := $(addprefix clean-py,$(PY_VERSIONS))
DATE_STRING := $(shell date +%Y.%m.%d)
THIS_MONTH_DATE := $(shell date +%Y.%m.01)
NEXT_MONTH_DATE := $(shell date -d "+1 month" +%Y.%m.01)
PATCHED_PIP_VERSION := $(shell awk '/__version__/{gsub(/"/,"",$$3); print $$3}' pipenv/patched/pip/__init__.py)
GITDIR_STAMPFILE := $(CURDIR)/.git-checkout-dir
create_git_tmpdir = $(shell mktemp -dt pipenv-vendor-XXXXXXXX 2>/dev/null || mktemp -d 2>/dev/null)
write_git_tmpdir = $(file > $(GITDIR_STAMPFILE),$(create_git_tmpdir))
get_checkout_dir = $(file < $(GITDIR_STAMPFILE))
get_checkout_subdir = $(addprefix $(get_checkout_dir), $(1))
pip-checkout-dir = $(get_checkout_dir)/patch-pip

format:
	black pipenv/*.py

.PHONY: install
install:
	pip install -e .

install.stamp: install
	@touch install.stamp

.PHONY: install-py%
install-py%: install.stamp
	@echo building for $(addprefix python, $(subst install-py,,$@))
	PIPENV_PYTHON=$(subst install-py,,$@) pipenv install --dev

install-virtualenvs.stamp: ${INSTALL_TARGETS}
	@touch install-virtualenvs.stamp

.PHONY: ramdisk
ramdisk: SIZE ?= 4g
ramdisk:
	sudo mkdir -p /mnt/ramdisk
	sudo mount -t tmpfs -o size=$(SIZE) tmpfs /mnt/ramdisk
	sudo chown -R ${USER}:${USER} /mnt/ramdisk

.PHONY: ramdisk-virtualenv
ramdisk-virtualenv: ramdisk
	[ ! -e "/mnt/ramdisk/.venv/bin/activate" ] && \
		python -m venv /mnt/ramdisk/.venv
	echo "/mnt/ramdisk/.venv" > $(venv_file)

.PHONY: virtualenv
virtualenv:
	[ ! -e $(venv_dir) ] && rm -rvf $(venv_file) && python -m venv $(venv_dir)
	@echo $(venv_dir) > $(venv_file)

.PHONY: test-install
test-install:
test-install: $(if $(RAMDISK), ramdisk-virtualenv virtualenv)
	. $(get_venv_path)/bin/activate && \
		python -m pip install --upgrade pip -e .[tests,dev] && \
		pipenv install --dev

.PHONY: submodules
submodules:
	git submodule sync
	git submodule update --init --recursive

# Run the tests within ramdisk by setting RAMDISK=1
# e.g make tests RAMDISK=1
.PHONY: tests
tests: parallel ?= -n auto
tests: suite ?=
tests: submodules test-install
	source $(get_venv_path)/bin/activate && \
		pipenv run pytest -ra $(parallel) -vvv --full-trace --tb=long $(suite)

.PHONY: vendor
vendor: virtualenv
	. $(get_venv_path)/bin/activate && \
		python -m pip install invoke && \
		python -m pip install -e .[dev] && \
		python -m invoke vendoring.update

.PHONY: test-specific
test-specific: submodules virtualenv test-install
	. $(get_venv_path)/bin/activate && pipenv run pytest -ra -k '$(tests)'

.PHONY: retest
retest: parallel ?= -n auto
retest: virtualenv submodules test-install
	. $(get_venv_path)/bin/activate && pipenv run pytest $(parallel) -ra -k 'test_check_unused or test_install_editable_git_tag or test_get_vcs_refs or test_skip_requirements_when_pipfile or test_editable_vcs_install or test_basic_vcs_install or test_git_vcs_install or test_ssh_vcs_install or test_vcs_can_use_markers' -vvv --full-trace --tb=long

.PHONY: build
build: install-virtualenvs.stamp install.stamp
	PIPENV_PYTHON=3.7 pipenv run python setup.py sdist bdist_wheel

.PHONY: update-version
update-version:
	@sed -i "s/^__version__ = .\+$\/__version__ = \"$(DATE_STRING)\"/g" ./pipenv/__version__.py

.PHONY: update-prerelease-version
update-prerelease-version:
	@sed -i "s/^__version__ = .\+$\/__version__ = \"$(THIS_MONTH_DATE).a1\"/g" ./pipenv/__version__.py

.PHONY: pre-bump
pre-bump:
	@sed -i "s/^__version__ = .\+$\/__version__ = \"$(NEXT_MONTH_DATE).dev0\"/g" ./pipenv/__version__.py

.PHONY: lint
lint:
	flake8 .

man:
	$(MAKE) -C docs $@

.PHONY: check
check: build.stamp
	pipenv run twine check dist/* && pipenv run check-manifest .

.PHONY: upload-test
upload-test: build
	twine upload --repository=testpypi dist/*

.PHONY: clean-py%
clean-py%:
	@echo "cleaning environment for $@..."
	PIPENV_PYTHON="$(subst clean-py,,$@)" pipenv --rm

.PHONY: cleanbuild
cleanbuild:
	@echo "cleaning up existing builds..."
	@rm -rf build/ dist/
	@rm -rf build.stamp

.PHONY: clean
clean:
	rm -rf install.stamp build.stamp install-virtualenvs.stamp .git-checkout-dir

.PHONY: gitclean
gitclean:
	@echo "Cleaning up git trees..."
	@rm -rf $(file < .git-checkout-dir)
	@echo "Cleaning up git checkout stamp"
	@rm -rf .git-checkout-dir

.git-checkout-dir:
	@echo "Creating git repo temp file"
	@echo "Creating git checkout stamp file at .git-checkout-dir"
	@echo $(file > $(CURDIR)/.git-checkout-dir,$(shell mktemp -dt pipenv-vendor-XXXXXXXX 2>/dev/null || mktemp -d 2>/dev/null))

.PHONY: clone-pip
clone-pip: .git-checkout-dir
	[ -e $(pip-checkout-dir) ] && echo "Pip already exists, moving on!" || git clone https://github.com/pypa/pip.git $(pip-checkout-dir) -b $(PATCHED_PIP_VERSION)

.PHONY: patch-pip
patch-pip: clone-pip
	@find $(CURDIR)/tasks/vendoring/patches/patched/ -regex ".*/pip[0-9]+.patch" -exec cp {} $(pip-checkout-dir) \;
	@sed -i -r 's:([a-b]\/)pipenv/patched/:\1src/:g' $(pip-checkout-dir)/*.patch
	@find $(CURDIR)/tasks/vendoring/patches/patched/ -regex ".*/_post-pip-[^/\.]*.patch" -exec cp {} $(pip-checkout-dir)/ \;
	@sed -i -r 's:([a-b]\/)pipenv/patched/not:\1src/:g' $(pip-checkout-dir)/_post-*.patch
	@cd $(pip-checkout-dir)/ && git apply --ignore-whitespace --verbose pip*.patch
	@echo "Head to $(pip-checkout-dir) to update the pip patches to the latest version"

.PHONY: patches
patches: patch-pip

.PHONY: reimport-pip-patch
reimport-pip-patch:
	@sed -i -r 's:([a-b]\/)src/:\1pipenv/patched/not:g' $(pip-checkout-dir)/_post-*.patch
	@sed -i -r 's:([a-b]\/)src/:\1pipenv/patched/:g' $(pip-checkout-dir)/pip*.patch
	@find $(pip-checkout-dir) -maxdepth 1 -regex ".*/pip[0-9]+.patch" -exec cp {} $(CURDIR)/tasks/vendoring/patches/patched/ \;
	@find $(pip-checkout-dir) -maxdepth 1 -regex ".*/_post-pip-[^/\.]*.patch" -exec cp {} $(CURDIR)/tasks/vendoring/patches/patched/ \;
