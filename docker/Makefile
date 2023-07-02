ALL_PYVERSIONS = 3.11-alpine 3.10-alpine 3.9-alpine 3.8-alpine 3.11 3.10 3.9 3.8


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
