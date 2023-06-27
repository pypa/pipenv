ifneq (,$(wildcard ./.env))
    include .env
	export
endif


docker-build:
	echo $(PYVERSION) $(PIPENV)
	docker build -t $(REGISTRY)/$(ORG)/$(IMG):$(TAG) --build-arg PYVERSION=$(PYVERSION) --build-arg VERSION=$(PIPENV) -f Dockerfile .


docker-push:
	docker push $(REGISTRY)/$(ORG)/$(IMG):$(TAG)
