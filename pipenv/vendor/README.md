# Vendored packages

These packages are copied as-is from upstream to reduce Pipenv dependencies.
They should always be kept synced with upstream. DO NOT MODIFY DIRECTLY! If
you need to patch anything, move the package to `patched` and generate a
patch for it using `git diff -p <dependency_root_dir>`. This patch belongs
in `./pipenv/tasks/vendoring/patches/patched/<packagename.patchdesc>.patch`.

To add a vendored dependency or to update a single dependency, add the package
name and version to `pipenv/vendor/vendor.txt`, for example:

```
appdirs==1.4.4
```

And the run the vendoring script:

```
python -m invoke vendoring.update
```

This will automatically download or pin if the package is already present,
and it will also download any necessary licenses (if available).
Note that this will not download any dependencies, you must add those each
individually.

When updating, ensure that the corresponding LICENSE files are still 
up-to-date.
