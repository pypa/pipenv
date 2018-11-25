# PEEP-003: New project creation

This PEEP describes a new `pipenv` command to create a new empty python package, along with VCS, and virtual environment.

☤

Starting a new python package requires manual repetitive steps. Although not every developer uses the same structure, many similarities exist. Automating
these steps will not only reduce verbosity, but also encourage good packaging practices, help new developers understand the python packaging structure, as well as provide a practical implementation to a standard/recommended package structure.


Inspired from Rust's [`cargo new`](https://doc.rust-lang.org/cargo/guide/creating-a-new-project.html), the command `pipenv new [OPTION] PACKAGE_NAME` executes all these steps at once, namely:
  - Create a root folder `PACKAGE_NAME`,
  - Create an empty package with a structure similar to [kennethreitz/setup.py](https://github.com/kennethreitz/setup.py),
  - Additionally to the previous structure, a `PACKAGE_NAME/tests` folder with an dummy test, a `PACKAGE_NAME/scripts` with a dummy script are included,
  - Initialize a VCS,
  - Initialize virtual environment and `Pipfile` (similar to `pipenv --two/three`).
