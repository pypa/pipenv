Added support for ``cool-down-period`` in the ``[pipenv]`` section of the Pipfile.
Setting ``cool-down-period = "30d"`` instructs the resolver to only consider
package versions uploaded at least the specified number of days ago, via pip's
``--uploaded-prior-to`` flag.
