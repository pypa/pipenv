Pipenv now enforces a wall-clock timeout on the resolver across both
the subprocess and in-process branches. The deadline is resolved with
the precedence ``[pipenv] resolver_timeout_seconds`` (Pipfile) >
``PIPENV_RESOLVER_TIMEOUT_S`` (env var) > default (1800 seconds), and
is stamped onto ``RequestMetadata.deadline_seconds`` so the resolver
subprocess sees the same value the parent uses for
``subprocess.wait(timeout=...)``. A hung resolver is now killed and a
structured error surfaced naming the override, instead of hanging
indefinitely. The in-process debug branch
(``PIPENV_RESOLVER_PARENT_PYTHON=1``) enforces the same deadline via
``SIGALRM`` on Unix; Windows continues to rely on the subprocess
path for enforcement.
