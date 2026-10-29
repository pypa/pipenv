# Resolver Backends

Pipenv resolves your `Pipfile` into a `Pipfile.lock` using a pluggable resolver backend. The backend decides *how* dependencies are resolved; the lockfile it produces has the same format whichever backend you use.

| Backend | Description |
|---------|-------------|
| `pip` | The default. Pipenv's vendored, patched copy of pip's resolver. |
| `pure-python` | An in-tree resolver that reads index metadata directly. |
| `uv` | Delegates resolution to [uv](https://docs.astral.sh/uv/), a fast resolver written in Rust. Requires `uv` on your `$PATH`. |

## Selecting a Backend

In order of precedence:

1. A command-line option: `--backend` on `pipenv lock`, or `--resolver` on any command that locks (`install`, `update`, `upgrade`, `uninstall`, `lock`):

   ```bash
   $ pipenv lock --backend uv
   $ pipenv install requests --resolver uv
   ```

2. The `PIPENV_RESOLVER` environment variable:

   ```bash
   $ PIPENV_RESOLVER=uv pipenv lock
   ```

3. The `resolver_backend` setting in the `[pipenv]` section of your `Pipfile`, which applies to everyone working on the project:

   ```toml
   [pipenv]
   resolver_backend = "uv"
   ```

If none of these is set, the `pip` backend is used.

## The uv Backend

### Installing uv

Pipenv does not bundle uv. Install it with any of:

```bash
$ pip install uv
$ pipx install uv
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

If the `uv` backend is selected and `uv` is not on your `$PATH`, locking fails with an error explaining how to install it. Pipenv never silently falls back to another backend.

### What It Does

The `uv` backend resolves with `uv pip compile` against your project's virtualenv interpreter, so it targets the same single environment the `pip` backend does (including the `python_full_version` from `[requires]`). It keeps Pipenv's semantics:

- **Index restriction.** A package without an `index` key resolves only from the first `[[source]]`. A package with `index = "name"` resolves only from that source. Other sources are never searched implicitly, which protects against dependency-confusion attacks.
- **Hashes.** Every distribution of each pinned version is hashed, so the lockfile installs on other platforms.
- **Markers.** Markers on `Pipfile` entries are kept and carried over to the dependencies those packages introduce. A package whose markers exclude the current platform is still recorded in the lockfile.
- **Categories.** Non-default categories such as `[dev-packages]` are resolved consistently with the versions locked for `[packages]`.
- **Credentials.** Credentials in source URLs, `.netrc` files, and `PIPENV_KEYRING_PROVIDER` work as they do with the `pip` backend.

Installation (`pipenv install`, `pipenv sync`) still uses pip, whichever backend produced the lockfile.

### Differences From the pip Backend

The `uv` backend picks the same versions as the `pip` backend in the vast majority of projects, but the lockfiles are not always byte-for-byte identical:

- The `pip` backend adds each package's `Requires-Python` to its `markers` (for example `python_version >= '3.9'`). The `uv` backend does not. These markers are always true for the environment the lockfile was created for.
- For a direct `file` URL dependency, the `uv` backend records only the hash of that file.
- Options passed with `--extra-pip-args` are ignored, with a warning.

Switching backends on an existing project can therefore produce a small lockfile diff on the next `pipenv lock`.
