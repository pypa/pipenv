# PEEP-006: add flag to save exact libraries' versions to Pipfile

PROPOSED

As suggested in [this issue](https://github.com/pypa/pipenv/issues/3441), it would be very convinient if there was a flag like in npm that, when doing `pipenv install`, made that the versions saved to Pipfile were the exact ones used, instead of `"*"`

Copying here some text from that issue that explains the problem a bit better:

> Example:
> pipenv install scipy would add scipy = "*" to the Pipfile.
>
> I would have expected a way to have scipy = "==1.2.0" to the Pipfile instead.
>
> I was wondering if this sort of functionality already exists and/or if there is any reason not to go this route.

