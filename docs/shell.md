# About Shell Configuration

Shells are typically misconfigured for subshell use, so ``$ pipenv shell --fancy`` may produce unexpected results. If this is the case, try ``$ pipenv shell``, which uses "compatibility mode", and will attempt to spawn a subshell despite misconfiguration.

A proper shell configuration only sets environment variables like ``PATH`` during a login session, not during every subshell spawn (as they are typically configured to do). In fish, this looks like this:

    if status --is-login
        set -gx PATH /usr/local/bin $PATH
    end

You should do this for your shell too, in your ``~/.profile`` or ``~/.bashrc`` or wherever appropriate.

The shell launched in interactive mode. This means that if your shell reads its configuration from a specific file for interactive mode (e.g. bash by default looks for a ``~/.bashrc`` configuration file for interactive mode), then you'll need to modify (or create) this file.

If you experience issues with ``$ pipenv shell``, just check the ``PIPENV_SHELL`` environment variable, which ``$ pipenv shell`` will use if available. For detail, see :ref:`configuration-with-environment-variables`.
