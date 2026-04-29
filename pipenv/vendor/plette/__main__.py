"""
A simple entry point which can be use to test Pipfiles

e.g.

python -m plette -f examples/Pipfile.valid.list 
python -m plette -f examples/Pipfile.valid.editable
# throws exception
python -m plette -f examples/Pipfile.invalid.list  

"""

import argparse

import tomlkit

from plette import Pipfile, Lockfile


parser = argparse.ArgumentParser()
parser.add_argument("-f", "--file", help="Input file")

args = parser.parse_args()

dest = args.file

with open(dest) as f:
    try:
        pipfile = Pipfile.load(f)
    except tomlkit.exceptions.EmptyKeyError:
        f.seek(0)
        lockfile = Lockfile.load(f)
