import subprocess
import sys


def test_help():
    output = subprocess.check_output(
        [sys.executable, '-m', 'pipenv.help'],
        stderr=subprocess.STDOUT,
    )
    assert output
