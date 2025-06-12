# Pipenv Package Manager Benchmark

This directory contains benchmarking tests for pipenv based on the [python-package-manager-shootout](https://github.com/lincolnloop/python-package-manager-shootout) project.

## Purpose

These benchmarks help validate that pipenv performance doesn't regress over time by testing common package management operations against a real-world dependency set from [Sentry's requirements](https://github.com/getsentry/sentry/blob/main/requirements-base.txt).

## Operations Benchmarked

- **tooling** - Installing pipenv using the current development version
- **import** - Converting requirements.txt to Pipfile format
- **lock** - Generating Pipfile.lock from dependencies
- **install-cold** - Installing packages with empty cache
- **install-warm** - Installing packages with populated cache
- **update** - Updating all packages to latest versions
- **add-package** - Adding a new package and updating lock file

## Usage

### Local Testing

```bash
# Run all benchmark operations
make benchmark

# Clean benchmark artifacts
make benchmark-clean

# Run individual operations
cd benchmarks
python benchmark.py                    # Run full benchmark suite
python benchmark.py setup              # Download requirements.txt
python benchmark.py tooling            # Benchmark pipenv installation
python benchmark.py import             # Benchmark requirements import
python benchmark.py lock-cold          # Benchmark lock with cold cache
python benchmark.py lock-warm          # Benchmark lock with warm cache
python benchmark.py install-cold       # Benchmark install with cold cache
python benchmark.py install-warm       # Benchmark install with warm cache
python benchmark.py update-cold        # Benchmark update with cold cache
python benchmark.py update-warm        # Benchmark update with warm cache
python benchmark.py add-package        # Benchmark adding a package
python benchmark.py stats              # Generate stats.csv
```

### CI Integration

The benchmarks run automatically in GitHub Actions on the `ubuntu-latest` runner as part of the CI pipeline. Results are:

- Displayed in the job summary with timing statistics
- Uploaded as artifacts for historical analysis
- Used to detect performance regressions

## Files

- `benchmark.py` - Main benchmark runner script
- `Pipfile` - Base Pipfile template (dependencies added during import)
- `requirements.txt` - Downloaded from Sentry's requirements-base.txt during setup
- `timings/` - Directory created during benchmarks to store timing data
- `stats.csv` - Generated CSV with benchmark results

## Dependencies

The benchmark uses Sentry's `requirements-base.txt` as a representative real-world dependency set. This includes packages like:

- Django and related packages
- Database connectors
- Serialization libraries
- HTTP clients
- Development tools

## Notes

- Benchmarks only run on Linux in CI to ensure consistent timing measurements
- System dependencies (libxmlsec1-dev, librdkafka-dev) are installed for Sentry requirements
- Cache clearing ensures cold/warm scenarios are properly tested
- Results include CPU time, memory usage, and I/O statistics
