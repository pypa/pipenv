# Credentials

## Injecting credentials into Pipfile via environment variables

Pipenv will expand environment variables (if defined) in your Pipfile. Quite
useful if you need to authenticate to a private PyPI:

    [[source]]
    url = "https://$USERNAME:${PASSWORD}@mypypi.example.com/simple"
    verify_ssl = true
    name = "pypi"

Luckily - pipenv will hash your Pipfile *before* expanding environment
variables (and, helpfully, will substitute the environment variables again when
you install from the lock file - so no need to commit any secrets! Woo!)

If your credentials contain special characters, make sure they are URL-encoded as specified in `rfc3986 <https://datatracker.ietf.org/doc/html/rfc3986>`_.

Environment variables may be specified as `${MY_ENVAR}` or `$MY_ENVAR`.

On Windows, `%MY_ENVAR%` is supported in addition to `${MY_ENVAR}` or `$MY_ENVAR`.

Environment variables in the URL part of requirement specifiers can also be expanded, where the variable must be in the form of `${VAR_NAME}`. Neither `$VAR_NAME` nor `%VAR_NAME%` is acceptable:

    [[package]]
    requests = {git = "git://${USERNAME}:${PASSWORD}@private.git.com/psf/requests.git", ref = "2.22.0"}

Keep in mind that environment variables are expanded in runtime, leaving the entries in `Pipfile` or `Pipfile.lock` untouched. This is to avoid the accidental leakage of credentials in the source code.

## Injecting credentials through keychain support

Private registries on Google Cloud, Azure and AWS support dynamic credentials using
the keychain implementation.

Pipenv supports this keychain implementation. It will automatically detect the
keychain implementation and use it to authenticate to the private registry.

### Google Cloud

Google Cloud supports private registries. You can find more information about
this here: https://cloud.google.com/artifact-registry/docs/python/authentication

In order to utilize, you need to install the `keyring` and `keyrings.google-artifactregistry` packages,
and they must be available in the same virtualenv that you intend to use Pipenv in.

    pipenv run pip install keyring keyrings.google-artifactregistry-auth

Depending on the way your keychain is structured, it may ask for user input.
Asking the user for input is disabled by default, and this may disable the keychain support completely.
If you want to work with private registries that use the keychain for authentication,
you may need to disable the "enforcement of no input".

**Note:** Please be sure that the keychain will really not ask for input.
Otherwise, the process will hang forever!:

    [[source]]
    url = "https://pypi.org/simple"
    verify_ssl = true
    name = "pypi"

    [[source]]
    url = "https://europe-python.pkg.dev/my-project/python/simple"
    verify_ssl = true
    name = "private-gcp"

    [packages]
    flask = "*"
    private-test-package = {version = "*", index = "private-gcp"}

    [pipenv]
    disable_pip_input = false

Above example will install `flask` and a private package `private-test-package` from GCP.
