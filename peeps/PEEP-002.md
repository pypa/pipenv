# PEEP-002: Specify options via environment variables

**ACCEPTED** (being implemented)

This PEEP describes an addition that would allow configuring Pipenv options via environment variables suitable especially for automated systems or CI/CD systems.

☤

Systems running not only on containerized solutions (like Kubernetes or OpenShift) are often parametrized via environment variables. The aim of this PEEP is to provide an extension to the current Pipenv implementation that would simplify parametrizing options passed via environment variables.

The current implementation requires most of the options to be passed via command line. It is possible to adjust some of the command line options via pre-defined names of environment variables (such as ``PIPENV_PYTHON``) but this approach does not allow to define environment variables for all of the options that can be possibly passed to Pipenv.

The proposed approach is to re-use existing options passing via environment variables avaliable in [click](http://click.pocoo.org/5/options/#values-from-environment-variables>) (bundled with Pipenv). All of the options for available Pipenv's sub-commands can directly pick options passed via environment variables:

```console
$ export PIPENV_INSTALL_DEPLOY=1
$ export PIPENV_INSTALL_VERBOSE=1
$ pipenv install
```

The naming schema for environment variables configuring options is following:

```
PIPENV_<SUBCOMMAND>_<OPTION_NAME>
```

where sub-command is an uppercase name of Pipenv's sub-command (such as `install`, `run` or others) and option name is the name of Pipenv's sub-command option all in uppercase. Any dashes are translated to underscores; flags accept `1` signalizing the flag to be present.

The naming schema guarantees no clashes for the already existing Pipenv configuration using environment variables.

The proposed configuration via environment variables is available for Pipenv sub-commands. Options supplied via command line have higher priority than the ones supplied via environment variables.

Author: Fridolín Pokorný <fridolin.pokorny@gmail.com>
