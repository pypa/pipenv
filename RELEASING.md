# Releasing Pipenv

We recognize that the pipenv release process is currently poorly managed. That's why this document seeks to streamline the release process, identify current complexities, and help eliminate existing single points of failure.

## Development Install

Any new release will require you to have the latest version of master installed in development mode:

```bash
$ git checkout master
$ git fetch origin
$ git pull
$ pipenv install --dev
```

## Make new releases of related libraries

A lot of pipenv depends on ancillary libraries. You may need to make new releases of:

 * [requirementslib](https://pypi.org/project/requirementslib/)
 * [pip-shims](https://pypi.org/project/pip-shims/)
 * [vistir](https://pypi.org/project/vistir/)
 * [pythonfinder](https://pypi.org/project/pythonfinder/)

## Updating Vendored Dependencies

This is the most complex element of releasing new versions of pipenv due to existing patches on current code. Currently the largest patchsets are maintained against [pip](https://github.com/pypa/pip).

You can begin by reviewing vendored dependencies which can be found in `pipenv/vendor/vendor.txt`, a file which is consumed by the automated vendoring process. These dependencies may have minor patches applied which can be found in `tasks/vendoring/patches/vendor`. Check PyPI for updates to the specified packages and increment the versions as needed, making sure to capture all dependencies in case any were added. It would be *very bad* to release without necessary dependencies, obviously.

Next you can consult `pipenv/patched/patched.txt` which enumerates the patched dependencies. Follow the same process, but be aware that you will need to rewrite patches for each dependency once you update (most likely) as they do tend to change somewhat substantially.


### Update Safety

Pipenv also includes a vendored copy of `safety` for checking for vulnerabilities against the `pyup.io` database. In order to update the `safety` package, run the following:

```console
$ inv vendoring.update-safety
```


### Updating patches

For larger libraries you can keep local clones of them and simply generate full patch sets in which you replace the updated path in pipenv when you are done making changes.  Here is an example of a script used from inside a local clone of `pip` to generate a patch and copy it to pipenv's local patches directory.

```bash
#!/usr/bin/bash
sed -i -r 's/([a-b]\/)(?:src\/)?(pip)/\1pipenv\/patched\/\2/g' diff.patch
cp diff.patch ../pipenv/tasks/vendoring/patches/patched/pip19.patch
```

## Updating Vendored Dependencies (continued)

Okay, now that's done, it's time to update vendored dependencies. You can install pipenv itself by moving to the source directory (`cd pipenv`) and running `pip install -e .`. Then you can run `pipenv install --dev` to install the development dependencies into a virtual environment.

Update the vendored dependencies by copying the `pipenv/vendor/vendor.txt` file to a new directory (e.g. `/tmp/vendor`) and unpinning all of the dependencies. Note there is a helper script for this:

```bash
$ pipenv run inv vendoring.unpin-and-update-vendored
```

This should unpin all vendored and patched dependencies and resolve them; ideally you would keep the file formatted so that we can see what depends on what, but this will tell you what can be updated & provide the latest versions.

To re-vendor and patch the vendored libraries, run the command:

```bash
$ pipenv run inv vendoring.update
```

This will automatically remove the `./pipenv/vendor/` and `./pipenv/patched/` directories and re-download and patch the specified dependencies. It will also attempt to download any relevant licenses. Once this is completed, run `git status` and inspect the output -- look through the `git diff` for anything that may cause breakages. If any licenses have been deleted, you will need to determine why they were not replaced by the license download tooling.

## Review Vendored Licenses


Make sure to read through any modified license files for changes -- note that we cannot redistribute code that is licensed under a [copyleft](https://en.wikipedia.org/wiki/Copyleft) license, such as the [GPL](https://en.wikipedia.org/wiki/GPL). Similarly, all vendored code **must** be licensed or it cannot be redistributed. If vendored libraries have become unlicensed or are no longer usable, suitable replacements will have to be found and potentially patched into the vendored dependencies. This may be a good time to consider simply including the dependency as an install requirement.

### TODO
Look into using a tool like https://fossa.com/ to help with this.


## Update Pipfile.lock

Now we will need to update the lockfile. This is required to ensure tests run against the latest versions of libraries. You will need to run the following:

```bash
# use the latest python here
$ export PIPENV_PYTHON=3.8
$ pipenv lock --dev
# Inspect the changes in a diff viewer, for example we should keep the older Python dependencies to use for running tests
# on completion, stage the relevant changes
$ export PIPENV_PYTHON=3.7
$ pipenv lock --keep-outdated --dev
# this helps avoid overwriting the entire lockfile and should introduce only the changes required to run tests on previous Python versions
# inspect the resulting lockfile and commit the changes
$ git commit
```

## Test locally

Test pipenv locally. If tests pass, you can go ahead and make a PR to merge whatever you want to release.

```bash
$ export PIPENV_PYTHON=3.8
$ pipenv install --dev && pytest -ra tests
```

## Check Spelling in Documentation

Pipenv now leverages `sphinxcontrib.spelling` to help ensure documentation does not contain typographical mistakes. To validate documentation, please make sure to rebuild and rectify any documentation issues before pushing the new release:

```console
$ pipenv shell
$ cd docs
$ make clean && make html
$ make spelling
```

Validate the results, adding any new exceptions to `docs/spelling_wordlist.txt`.


## Releasing

1. Set a version: `pipenv run inv release.bump-version --trunc-month --pre --tag=a` - this will truncate the current month, creating an alpha pre-release, e.g. `2020.4.1a1`
   a. **Note**: You can pass `--tag=b` or `--tag=rc` here as well
2. `make check` - This has the side-effect of producing wheels
3. `make tests`- Runs tests locally
4. `make upload-test` - This uploads artifacts to test-pypi
5. Consume the version on test pypi, ensure that version is functioning.
6. Push the pre-release to github & wait for CI to pass
7. Create a new tag, e.g. `v2020.4.1a1` and push it to github -- this can be achieved via `pipenv run inv release.tag-version --push`
8. The github action will automatically build and push the prerelease to `PyPI`
9.  Once a release is pushed, the action will update `master` with a new `dev` version
10. Review any pull requests and issues that should be resolved before releasing the final version
11. The process is identical for releasing a standard release, except the `release.bump-version` command is called without any arguments.


If in doubt, follow the basic instructions below.

## Uploading the release

1. Get set up on [Test PyPI](https://test.pypi.org/)
2. [Use Test PyPI](https://packaging.python.org/guides/using-testpypi/) to upload the package, make sure the `README` renders, test that it installs okay, and so on
3. Get credentials to co-maintain the pipenv project on PyPI.org -- **SPOF alert**
4. Set the version number to [a pre-release identifier](https://www.python.org/dev/peps/pep-0440/#pre-release-separators)
5. Package and upload pipenv [to PyPI](https://pypi.org/project/pipenv/#history) as a pre-release/alpha
6. Publicize on distutils-sig, [Discourse](https://discuss.python.org/c/packaging), and the relevant GitHub issue(s)
    a. write up diplomatic notification
7. Recruit manual testing ([example](https://pad.sfconservancy.org/p/help-test-pipenv-2020-03-26)) for workflows we don't account for
8. Wait a week, then update version number to a canonical release and re-release on PyPI.org
10. Publicize on lists, Discourse, GitHub issues

## Looking ahead

Most of the pipenv related ecosystem libraries are using [GitHub actions](https://github.com/sarugaku/vistir/blob/master/.github/workflows/pypi_upload.yml) to automate releases when tags are pushed. Most likely we will look to move in this direction and simplify the process.
