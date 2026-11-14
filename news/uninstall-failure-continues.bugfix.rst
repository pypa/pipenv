Fix ``pipenv clean`` and ``pipenv uninstall`` aborting with a traceback at the first failing ``pip uninstall`` instead of continuing with the remaining packages and exiting non-zero.
