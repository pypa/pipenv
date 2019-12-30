# PEEP-006: Allow for local installations of libraries

This PEEP adds an additional option to allow for local installations of libraries.

☤

## Introduction

It is often necessary to be able to package an application as an archive with just the application and it's dependencies, and nothing else. There are numerous reason for doing this, but one of the main examples is certain services require specific packaging of the application (e.g. AWS Lambda). This means that we should be able to have the virtual environment in one place for IDEs to use (e.g. globally, or locally in a .venv directory as current is the functionality), while the libraries themselves are in it's in another directory, e.g. in `vendor`.

This option is currently already supported in pip using the `--target <target-dir>` option. E.g.
```
$ pip install -r requirements.txt -t vendor
```

## Proposal

I propose we add a new `--target <target-dir>` option to `pipenv install` command. This would, in addition to the normal installation of the python dependencies, install the dependencies in the target directory (argument for `--target` would be required).

This would allow for the following scenarios:

```
$ pipenv install --target vendor
<clipped>
$ ls
src Pipfile Pipfile.lock vendor
$ ls vendor
bin  certifi  certifi-2019.11.28.dist-info  chardet  chardet-3.0.4.dist-info  idna  idna-2.8.dist-info  requests  requests-2.22.0.dist-info  urllib3  urllib3-1.25.7.dist-info
```

In addition, this option should be specifyable within a new section inside Pipfile as follows:

```toml
[global]
target = 'vendor'
```

The above would have the same effect as the option `--target vendor`.

## Alternative considerations

If adding a new section to the `Pipfile` proves to be a bigger task than necessary for 1 single option, an alternative option would be to specify the target on a per dependency basis. This however could get very cumbersome as it requires adding and/or removing this option for each package.
