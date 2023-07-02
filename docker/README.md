# Public docker images

Build all images with:
```
$ make build-all PIPENV=2023.07.3
```
Build a single image with with:

```
$ make docker-build docker-push TAG=3.11-alpine-v2023-6-26 PYVERSION=3.11-alpine PIPENV=2023.6.26
```
