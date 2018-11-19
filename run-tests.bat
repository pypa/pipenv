rem imdisk  -a -s 964515b -m R: -p "/FS:NTFS /Y"

virtualenv R:\.venv
R:\.venv\Scripts\pip install -e . --upgrade --upgrade-strategy=only-if-needed
R:\.venv\Scripts\pipenv install --dev
git submodule sync && git submodule update --init --recursive
SET RAM_DISK=R: && R:\.venv\Scripts\pipenv run pytest -n auto -v tests --tap-stream > report.tap
