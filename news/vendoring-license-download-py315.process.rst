Fix the vendoring license download on Python 3.15 CI runners:
install ``setuptools`` for ``--no-build-isolation`` sdist builds,
skip ``# via`` annotation lines in ``vendor.txt``,
and find the missing build backend anywhere in pip's error output.
