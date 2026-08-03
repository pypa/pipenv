Added a configurable timeout for the resolver subprocess invoked by
``pipenv install``, ``pipenv lock``, and ``pipenv sync``. A hung mirror or
stuck pip download previously caused the resolver to block forever from
the user's perspective; the wait is now bounded by
``PIPENV_RESOLVER_TIMEOUT_S`` (default ``1800`` seconds = 30 minutes,
chosen generously so normal resolutions are unaffected). On timeout the
subprocess is killed and a clear error is surfaced that names the
environment variable so users with legitimately large resolutions can
extend it.
