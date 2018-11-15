# PEEP-003: .env file loading policy

This PEEP describes two new project settings and one new environment variable 
that influence on Pipenv's behavior on .env file loading.

☤

There are at least two cases when Pipenv's behavior at .env file loading is annoying.

### Case 1: loading .env file

Developer uses some library which supports .env files (Flask for example) and wants to use 
.env file loader embedded in it.

With Pipenv installed .env file will be loaded twice. There is `PIPENV_DONT_LOAD_ENV` 
environment variable to not to load .env file by Pipenv but user have to know about 
project policy on .env file loading and have to care about it all the time.

Project setting `dont_load_env` is suggested to not to load .env file by default 
but such behavior still can be overwritten by `PIPENV_DONT_LOAD_ENV` environment variable:

```
[pipenv]
dont_load_env = true
```

### Case 2: overriding current environment variables by .env file

Developer has .env file within project and do not want his/her current environment variables are 
overridden by .env file. Currently such behavior is hardcoded in Pipenv and cannot be configured.

Project setting `dont_override_env` and environment variable `PIPENV_DONT_OVERRIDE_ENV` are suggested 
to not to override current environment variables by .env file:

```
[pipenv]
dont_override_env = true
```

---

All these settings are suggested for project level (Pipfile) so user (especially new project developer) 
wouldn't have to know about project policy on .env file loading as it can be implicit and hidden inside project.
