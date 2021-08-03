from pipenv.patched.notpip._internal.utils.appdirs import user_cache_dir

# The user_cache_dir helper comes straight from pipenv.patched.notpip itself
CACHE_DIR = user_cache_dir("pip-tools")
