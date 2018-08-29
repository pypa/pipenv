# Taken from pip: https://github.com/pypa/pip/blob/95bcf8c5f6394298035a7332c441868f3b0169f4/src/pip/_vendor/Makefile
all: clean vendor

clean:
	@# Delete vendored items
	find . -maxdepth 1 -mindepth 1 -type d -exec rm -rf {} \;

vendor:
	@# Install vendored libraries
	pip install -t . -r vendor.txt

	@# Cleanup .egg-info directories
	rm -rf *.egg-info
	rm -rf *.dist-info
