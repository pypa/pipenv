rem imdisk -a -s 2104515b -m R: -f C:\my_disk.ima -p "/FS:NTFS /C /Y"


rem virtualenv R:\.venv
rem R:\.venv\Scripts\pip install -e . --upgrade --upgrade-strategy=only-if-needed
rem R:\.venv\Scripts\pipenv install --dev

SET RAM_DISK=R:&& SET PYPI_VENDOR_DIR=".\tests\pypi\" && R:\.venv\Scripts\pipenv run pytest -n auto -v tests
rem --tap-stream
