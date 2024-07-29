# Locking Dependencies

Locking dependencies in Pipenv ensures that your project's dependencies are consistent across different environments by creating a `Pipfile.lock` file. This file contains the exact versions of all dependencies, making your builds deterministic and reproducible.

## Creating a Lock File

Pipenv will automatically generate a `Pipfile.lock` file when you install dependencies using the `pipenv install` command. This file contains the specific versions of all installed packages and their dependencies.

```bash
pipenv install requests
```

To completely update a `Pipfile.lock` file based on the currently available packages and your `Pipfile` specifiers, run the following command:

    pipenv lock


## Installing from a Lock File

When you have a `Pipfile.lock` file in your project, you can install the exact dependencies specified in the lock file with:

    pipenv install

## Updating Lock Files

When you need to update your dependencies, you can update a subset of lock file with:

    pipenv upgrade mypackage==1.2.3

This command updates all dependencies to their latest compatible versions and regenerates the `Pipfile.lock`.

Should you want `pipenv` to also install the upgraded packages, you can run the following command:

    pipenv update mypackage==1.2.3

## Viewing Locked Dependencies

You can view the currently locked dependencies and their versions with:

    pipenv graph

This command outputs a dependency graph, showing all locked packages and their dependencies.

## Best Practices

- **Commit Your `Pipfile.lock`:** Always commit your `Pipfile.lock` file to version control to ensure that your team members and CI/CD pipelines use the same dependencies.
- **Regularly Update Dependencies:** Periodically update your dependencies to include the latest patches and improvements while ensuring compatibility.
- **Review Dependency Changes:** When updating dependencies, review the changes in the `Pipfile.lock` to understand the impact on your project.

## Troubleshooting

### Common Issues

- **Dependency Conflicts:** If you encounter dependency conflicts, you may need to adjust your `Pipfile` or manually resolve the conflicts before locking again.   Run with the `--verbose` flag to get more information about the conflict.
- **Installation Errors:** Ensure that your `Pipfile.lock` is not corrupted and that you have the necessary permissions to install the dependencies.  Check for common system dependencies when building sdist packages.

### Helpful Commands

- **Check for Dependency Issues:**

    ```bash
    pipenv check
    ```

    This command checks for security vulnerabilities and other issues in your dependencies.

- **Clear Caches:**

    ```bash
    pipenv --clear
    ```

    This command clears Pipenv’s caches, which can resolve some installation issues.

## Supplying additional arguments to the pipenv resolver

You can supply additional arguments to the pipenv resolver by supplying `--extra-pip-arg` to the `install` command.  For example, `pipenv install --extra-pip-args="--platform=win_amd64 --target /path/to/my/target`.

```bash

## Conclusion

Locking in Pipenv is a powerful feature that ensures your Python project’s dependencies are consistent, secure, and reproducible. By understanding and utilizing Pipenv’s locking mechanism, you can avoid many common dependency management issues and ensure your projects run smoothly across different environments.

```note
Locking ensures that all dependencies are resolved and installed in a consistent manner. This helps avoid issues where different versions of dependencies might introduce bugs or inconsistencies in your project.
