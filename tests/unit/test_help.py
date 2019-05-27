import os
import subprocess
import sys


def test_help():
    output = subprocess.check_output(
        [sys.executable, '-m', 'pipenv.help'],
        stderr=subprocess.STDOUT, env=os.environ.copy(),
    )
    assert output


def test_count_of_description_pre_option():
    test_command = 'pipenv install --help'
    test_line = '--pre Allow pre-releases.'
    out = subprocess.Popen(test_command.split(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, _ = out.communicate()
    lines = stdout.decode().split('\n')
    count = 0
    for line in lines:
        if line.strip().split() == test_line.split():
            count += 1
    assert count == 1
