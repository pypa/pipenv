# PEEP-003: Dedicated fields for source credentials

This PEEP proposes to add dedicated fields to contain credentials that will be
url-encoded for a private index.

☤

For now, the easiest way to install packages from a private index is to use
environment variables in the Pipfile:

```
[[source]]
url = "https://$USERNAME:${PASSWORD}@mypypi.example.com/simple"
verify_ssl = true
name = "pypi"
```

But these variables may contain special characters that need to be encoded. For
instance:

```bash
USERNAME="my#username"
```

This can be done manually with [`urllib.parse.quote()`](https://docs.python.org/3.7/library/urllib.parse.html#urllib.parse.quote)
for instance, but it makes the process less smooth for the user.

This PEEP proposes to add fields to store credentials that will be encoded by
pipenv:

```
[[source]]
url = "https://mypypi.example.com/simple"
verify_ssl = true
name = "pypi"
username = "$USERNAME"
password = "$PASSWORD"
```

```bash
USERNAME="my#username"; PASSWORD="xxx/yyy"; pipenv install
```

We cannot automatically encode credentials passed in the `url` fields as they
may have already been encoded. By using dedicated fields, we make it clear that
the credentials will be encoded by pipenv.
