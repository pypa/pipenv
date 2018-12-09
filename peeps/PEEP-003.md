# PEEP-003: Allowing `pipenv sync` to remove packages

`pipens sync` should be allowed to uninstall packages that have been removed from the `Pipfile.lock` file.

☤

At the moment, if packages have been removed from `Pipfile.lock`, a subsequent `pipenv sync` wouldn't remove them from the environment. Consequently, an update of the environment from `Pipile.lock` is only possible via two commands: `pipenv clean` and `pipenv sync`.

This is somewhat unintuitive, as the name `sync` intuitively suggests that the update works in both ways: adding and removing packages.

It would make sense to make the default behavior of `pipenv sync` to produce an environment that exactly corresponds to the content of the `Pipfile.lock` file. That is, `pipenv sync` should be allowed to both install and uninstall packages.

In addition, a flag such as `--install-only` should be added that would only install new packages but not uninstall those that have been removed from `Pipfile.lock`.


