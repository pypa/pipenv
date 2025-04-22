Make safety an optional dependency via extras

- Removed vendored safety package from pipenv/patched
- Added safety as an optional dependency via pipenv[safety]
- Modified check.py to prompt for safety installation if not present
- Safety installation will not modify user's Pipfile or lockfile
