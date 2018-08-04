# Vendored packages

These packages are copied as-is from upstream to reduce Pipenv dependencies.
They should always be kept synced with upstream. DO NOT MODIFY DIRECTLY! If
you need to patch anything, move the package to `patched` and generate a
patch for it using `git diff -p <dependency_root_dir>`. This patch belongs
in `./pipenv/tasks/vendoring/patches/patched/<packagename.patchdesc>.patch`.

To add a vendored dependency or to update a single dependency, use the
vendoring scripts:
```
    pipenv run inv vendoring.update --package="pkgname==versionnum"
```

This will automatically pin the package in `./pipenv/vendor/vendor.txt`
or it will update the pin if the package is already present, and it will
then update the package and download any necessary licenses (if available).
Note that this will not download any dependencies, you must add those each
individually.

When updating, ensure that the corresponding LICENSE files are still 
up-to-date.
