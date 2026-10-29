ALL_PYVERSIONS = 3.15-alpine 3.14-alpine 3.13-alpine 3.12-alpine 3.11-alpine 3.15 3.14 3.13 3.12 3.11


ifneq (,$(wildcard ./.env))
    include .env
	export
endif


docker-build:
	echo $(PYVERSION) $(PIPENV)
	docker build -t $(REGISTRY)/$(ORG)/$(IMG):$(TAG) --build-arg PYVERSION=$(PYVERSION) --build-arg VERSION=$(PIPENV) -f Dockerfile .


docker-push:
	docker push $(REGISTRY)/$(ORG)/$(IMG):$(TAG)


build-all:
	$(foreach var,$(ALL_PYVERSIONS), make docker-build docker-push TAG=$(var)-$(PIPENV) PYVERSION=$(var) PIPENV=$(PIPENV);)
