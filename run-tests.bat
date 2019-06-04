rem If you want to use a ramdisk, use this section:

rem imdisk -a -s 4G -m R: -p "FS:NTFS /y"
rem if you are using a ram disk, you should comment the following substitution line out
subst R: %TEMP%

set TMP=R:\\
set TEMP=R:\\
set WORKON_HOME=R:\\
set RAM_DISK=R:\\

R:\.venv\Scripts\pip install -e .[test] --upgrade --upgrade-strategy=only-if-needed
R:\.venv\Scripts\pipenv install --dev
git submodule sync && git submodule update --init --recursive
R:\.venv\Scripts\pipenv run pytest -n auto -v tests
