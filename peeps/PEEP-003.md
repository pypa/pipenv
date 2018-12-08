# PEEP-003: Allowing `pipenv sync` to remove packages

`pipens sync` should be allowed to uninstall packages that have been removed from the `Pipfile.lock` file.

☤

At the moment, if packages have been removed from `Pipfile.lock`, a subsequent `pipenv sync` wouldn't remove them from the environment. Consequently, an update of the environment from `Pipile.lock` is only possible via two commands: `pipenv clean` and `pipenv sync`.

It would make sense to add a flag to `pipenv sync` to allow this to happen in one operation. Also, the name `sync` intuitively suggests that the update works in both ways: adding and removing packages. So that the current behavior might be somewhat unintuitive. Adding the flag would make it more intuitive, at least with the flag.
