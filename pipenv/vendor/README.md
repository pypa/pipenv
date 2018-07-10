# Vendored packages

These packages are copied as-is from upstream to reduce Pipenv dependencies.
They should always be kept synced with upstream. DO NOT MODIFY DIRECTLY! If
you need to patch anything, move the package to `patched`.

## Updatating Vendored Packages

Requires:

- [invoke](https://pypi.org/project/invoke/)

Modify the pip requirements file `vendor.txt`. Reference the [pip
documenation](https://pip.pypa.io/en/stable/user_guide/#requirements-files).
Execute the vendoring update script:

```$ invoke vendoring.update```

## Known vendored versions:

- python-dotenv: 0.8.2
