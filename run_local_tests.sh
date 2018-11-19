#!/bin/bash
owner=$USER
IFS=' ' read -a groups <<< $(groups)
group=${groups[0]}
python=$(python -c "import sys; print(sys.executable)")
python2=$(python2.7 -c "import sys; print(sys.executable)")
#python3=$(pyenv which python3.7)
ramdisk="/mnt/ramdisk"
venv_path="$ramdisk/.venv"
venv_bin="$venv_path/bin"
# pip="$venv_bin/pip"
# pipenv="$venv_bin/pipenv"
py="$venv_bin/python"
pip="$py -m pip"
pipenv="$py -m pipenv"
venv2_path="$ramdisk/.venv2"
# pipenv2="$venv2_bin/pipenv"
# pip2="$venv2_bin/pip"
venv2_bin="$venv2_path/bin"
py2="$venv2_bin/python"
pip2="$py2 -m pip"
pipenv2="$py2 -m pipenv"
#venv3_path="$ramdisk/.venv3"
#venv3_bin="$venv3_path/bin"
#pip3="$venv3_bin/pip"
#pipenv3="$venv3_bin/pipenv"


export RAM_DISK="/mnt/ramdisk/"

[ ! -e $venv_path ] && sudo mount -t ramfs -o size=2g ramfs $ramdisk \
    && sudo chown -R $owner:$group $ramdisk

[ ! -e $venv_path ] && python -m virtualenv --python=$python $venv_path \
    && VIRTUAL_ENV="$venv_path" $pip install -e . \
    && VIRTUAL_ENV="$venv_path" $pipenv run pip install -e . \
    && VIRTUAL_ENV="$venv_path" $pipenv install --dev

[ ! -e $venv2_path ] && python -m virtualenv --python=$python2 $venv2_path \
    && VIRTUAL_ENV="$venv2_path" $pip2 install pathlib2 -e . \
    && VIRTUAL_ENV="$venv2_path" $pipenv2 run pip install -e . \
    && VIRTUAL_ENV="$venv2_path" $pipenv2 install --dev

#[ ! -e $venv3_path ] && python -m virtualenv --python=$python3 $venv3_path \
    #&& $pip3 install -e . \
    #&& $pipenv3 run pip install -e . \
    #&& $pipenv3 install --dev


#export PYPI_VENDOR_DIR="$(pwd)/tests/pypi/"
PIP_PROCESS_DEPENDENCY_LINKS=1 && VIRTUAL_ENV="$venv2_path" $pipenv run pytest tests/ $@ 2>&1
PIP_PROCESS_DEPENDENCY_LINKS=1 && VIRTUAL_ENV="$venv2_path" $pipenv2 run pytest tests/ $@ 2>&1
#$pipenv run pytest -v -n 4 --ignore=pipenv/vendor --ignore=pipenv/patched --ignore=build --ignore=tests/pypi --ignore=tests/pytest-pypi/pypi -p tests.pytest-pypi.pytest_pypi tests/ $@ 2>&1
#$pipenv2 run pytest -v -n 4 --ignore=pipenv/vendor --ignore=pipenv/patched --ignore=build --ignore=tests/pypi --ignore=tests/pytest-pypi/pypi -p tests.pytest-pypi.pytest_pypi tests/ $@ 2>&1
#$pipenv3 run pytest -v -n 4 --ignore=pipenv/vendor --ignore=pipenv/patched tests/ $@ 2>&1
#    && /mnt/ramdisk/.venv/bin/pip install dist/pipenv-11.10.1.dev1-py2.py3-none-any.whl \
#    && /mnt/ramdisk/.venv/bin/pipenv run pip install dist/pipenv-11.10.1.dev1-py2.py3-none-any.whl \
