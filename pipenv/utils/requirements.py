import re
from typing import Tuple
from urllib.parse import quote

from pipenv.patched.pip._internal.utils.misc import _transform_url, split_auth_from_netloc


def redact_netloc(netloc: str) -> str:
    """
    Replace the sensitive data in a netloc with "****", if it exists, unless it's an environment variable.

    For example:
        - "user:pass@example.com" returns "user:****@example.com"
        - "accesstoken@example.com" returns "****@example.com"
        - "${ENV_VAR}:pass@example.com" returns "${ENV_VAR}:****@example.com" if ${ENV_VAR} is an environment variable
        - "git@github.com" returns "git@github.com" (standard SSH username preserved)

    Provenance: deliberate fork of
    ``pip._internal.utils.misc.redact_netloc``. Two intentional
    behavioural divergences from the pip-internal version:

    1. ``${ENV_VAR}`` placeholders in user/password are preserved
       (pip's version unconditionally rewrites both to ``****``).
    2. Standard SSH usernames (``git``) are preserved
       (pip's version has no such allowlist).

    Both divergences are user-visible (they appear in CLI output and in
    the generated ``Pipfile.lock``). Do not replace with the
    pip-internal version -- see ``docs/dev/initiative-b-triage.md``,
    section "Why we don't just ``from pip._internal.utils.misc import
    redact_*``", for the full rationale.
    """
    # Standard SSH usernames that should not be redacted
    STANDARD_SSH_USERNAMES = ("git",)

    netloc, (user, password) = split_auth_from_netloc(netloc)
    if user is None:
        return netloc
    if password is None:
        # Check if user is an environment variable or a standard SSH username
        if not re.match(r"\$\{\w+\}", user) and user not in STANDARD_SSH_USERNAMES:
            # If not, redact the user
            user = "****"
        password = ""
    else:
        # Check if password is an environment variable
        if not re.match(r"\$\{\w+\}", password):
            # If not, redact the password
            password = ":****"
        else:
            # If it is, leave it as is
            password = ":" + password
        user = quote(user)
    return f"{user}{password}@{netloc}"


def redact_auth_from_url(url: str) -> str:
    """Replace the password in a given url with ****.

    Provenance: deliberate fork of
    ``pip._internal.utils.misc.redact_auth_from_url``. This is a
    one-line wrapper around ``redact_netloc``; the divergence from
    pip's version lives in our :func:`redact_netloc` (env-var
    placeholders preserved; standard SSH usernames like ``git``
    preserved). Do not replace with the pip-internal version -- see
    ``docs/dev/initiative-b-triage.md`` for the full rationale.
    """

    def _redact_netloc_wrapper(netloc: str) -> Tuple[str]:
        return (redact_netloc(netloc),)

    return _transform_url(url, _redact_netloc_wrapper)[0]
