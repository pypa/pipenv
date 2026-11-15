Uninstall editable packages by their resolved distribution name instead of passing
editable install arguments to pip, so ``pipenv uninstall -e ./package`` also
removes the installed package from the environment.
