#!/usr/bin/env python3
"""
Pipenv benchmark runner based on python-package-manager-shootout.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None


OPERATIONS = (
    "setup",
    "tooling",
    "import",
    "lock-cold",
    "lock-warm",
    "install-cold",
    "install-warm",
    "update-cold",
    "update-warm",
    "add-package",
    "stats",
)

TIMED_STATS = (
    "tooling",
    "import",
    "lock-cold",
    "lock-warm",
    "install-cold",
    "install-warm",
    "update-cold",
    "update-warm",
    "add-package",
)


def subprocess_env(profile_resolver: bool = False):
    """Get environment variables for subprocess calls with CI-friendly settings."""
    env = os.environ.copy()
    # Ensure pipenv doesn't wait for user input.
    env["PIPENV_YES"] = "1"
    env["PIPENV_NOSPIN"] = "1"
    # Force pipenv to create its own venv, not use any existing one.
    env["PIPENV_IGNORE_VIRTUALENVS"] = "1"
    # Suppress courtesy notices.
    env["PIPENV_VERBOSITY"] = "-1"
    if profile_resolver:
        # Keep resolver work in the profiled parent process for local diagnosis.
        env["PIPENV_RESOLVER_PARENT_PYTHON"] = "1"
    return env


@dataclass
class TimingRecord:
    stat: str
    iteration: int
    command: list[str]
    elapsed_time: float
    system: float
    user: float
    cpu_percent: float
    max_rss: int
    inputs: int
    outputs: int
    returncode: int
    profile: str | None = None

    def timing_values(self) -> list[str]:
        return [
            f"{self.elapsed_time:.3f}",
            f"{self.system:.3f}",
            f"{self.user:.3f}",
            f"{self.cpu_percent:.1f}",
            str(self.max_rss),
            str(self.inputs),
            str(self.outputs),
        ]

    def timing_line(self) -> str:
        return ",".join(self.timing_values()) + "\n"


def _usage_snapshot():
    if resource is None:
        return None
    return resource.getrusage(resource.RUSAGE_CHILDREN)


def _usage_delta(
    before, after, elapsed: float
) -> tuple[float, float, float, int, int, int]:
    if before is None or after is None:
        return 0.0, 0.0, 0.0, 0, 0, 0

    user = max(after.ru_utime - before.ru_utime, 0.0)
    system = max(after.ru_stime - before.ru_stime, 0.0)
    cpu_percent = ((user + system) / elapsed * 100.0) if elapsed else 0.0
    inputs = max(after.ru_inblock - before.ru_inblock, 0)
    outputs = max(after.ru_oublock - before.ru_oublock, 0)
    # ru_maxrss from RUSAGE_CHILDREN is a cumulative high-water mark across
    # child processes, not a per-command measurement, so do not report it as
    # if it belonged to the command being benchmarked.
    return system, user, cpu_percent, 0, int(inputs), int(outputs)


class PipenvBenchmark:
    def __init__(
        self,
        benchmark_dir: Path,
        *,
        profile: bool = False,
        output_json: Path | None = None,
        force_setup: bool = False,
    ):
        self.benchmark_dir = benchmark_dir
        self.timings_dir = benchmark_dir / "timings"
        self.timings_dir.mkdir(exist_ok=True)
        self.requirements_url = (
            "https://raw.githubusercontent.com/getsentry/sentry/"
            "51281a6abd8ff4a93d2cebc04e1d5fc7aa9c4c11/requirements-base.txt"
        )
        self.test_package = "goodconf"
        self.profile = profile
        self.output_json = output_json
        self.force_setup = force_setup
        self.records: list[TimingRecord] = []
        self.timing_samples: dict[str, list[TimingRecord]] = {}

    def _profiled_command(
        self, command: list[str], timing_file: str, iteration: int
    ) -> tuple[list[str], Path | None, bool]:
        if not self.profile:
            return command, None, False

        stat = timing_file.removesuffix(".txt")
        profile_path = self.timings_dir / f"{stat}.{iteration}.prof"

        if command and command[0] == "pipenv":
            profiled = [
                sys.executable,
                "-m",
                "cProfile",
                "-o",
                str(profile_path),
                "-m",
                "pipenv",
                *command[1:],
            ]
            return profiled, profile_path, True

        if command and Path(command[0]).resolve() == Path(sys.executable).resolve():
            profiled = [
                sys.executable,
                "-m",
                "cProfile",
                "-o",
                str(profile_path),
                *command[1:],
            ]
            return profiled, profile_path, False

        return command, None, False

    def _write_timing_file(self, path: Path, values: list[str]) -> None:
        with open(path, "w") as f:
            f.write(",".join(values) + "\n")

    def _record_timing(self, record: TimingRecord, timing_file: str) -> None:
        self.records.append(record)
        samples = self.timing_samples.setdefault(record.stat, [])
        samples.append(record)

        self._write_timing_file(
            self.timings_dir / f"{record.stat}.{record.iteration}.txt",
            record.timing_values(),
        )

        aggregate_values = [
            f"{statistics.median(sample.elapsed_time for sample in samples):.3f}",
            f"{statistics.median(sample.system for sample in samples):.3f}",
            f"{statistics.median(sample.user for sample in samples):.3f}",
            f"{statistics.median(sample.cpu_percent for sample in samples):.1f}",
            str(int(statistics.median(sample.max_rss for sample in samples))),
            str(int(statistics.median(sample.inputs for sample in samples))),
            str(int(statistics.median(sample.outputs for sample in samples))),
        ]
        self._write_timing_file(self.timings_dir / timing_file, aggregate_values)

    def run_timed_command(
        self,
        command: list[str],
        timing_file: str,
        cwd: Path | None = None,
        timeout: int = 600,
    ) -> tuple[float, int]:
        """Run a command and measure execution time."""
        if cwd is None:
            cwd = self.benchmark_dir

        stat = timing_file.removesuffix(".txt")
        iteration = len(self.timing_samples.get(stat, [])) + 1
        command_to_run, profile_path, profile_resolver = self._profiled_command(
            command, timing_file, iteration
        )

        env = subprocess_env(profile_resolver=profile_resolver)

        print(f"  Running: {' '.join(command_to_run)}", flush=True)
        before_usage = _usage_snapshot()
        start_time = time.perf_counter()

        # Use Popen with communicate() to avoid pipe buffer deadlock
        # that can occur with capture_output=True on commands with lots of output.
        process = subprocess.Popen(
            command_to_run,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            stdout, stderr = process.communicate(timeout=timeout)
            elapsed = time.perf_counter() - start_time
            after_usage = _usage_snapshot()
            returncode = process.returncode
            system, user, cpu_percent, max_rss, inputs, outputs = _usage_delta(
                before_usage, after_usage, elapsed
            )

            if returncode != 0:
                print(
                    f"  Command failed after {elapsed:.3f}s: "
                    f"{' '.join(command_to_run)}"
                )
                print(f"  Return code: {returncode}")
                if stderr and stderr.strip():
                    print("  Error output:")
                    for line in stderr.strip().split("\n"):
                        print(f"    {line}")
                if stdout and stdout.strip():
                    print("  Stdout:")
                    for line in stdout.strip().split("\n"):
                        print(f"    {line}")
                raise subprocess.CalledProcessError(
                    returncode, command_to_run, stdout, stderr
                )

            record = TimingRecord(
                stat=stat,
                iteration=iteration,
                command=command_to_run,
                elapsed_time=elapsed,
                system=system,
                user=user,
                cpu_percent=cpu_percent,
                max_rss=max_rss,
                inputs=inputs,
                outputs=outputs,
                returncode=returncode,
                profile=str(profile_path) if profile_path else None,
            )
            self._record_timing(record, timing_file)

            print(f"  Completed in {elapsed:.3f}s")
            if profile_path:
                print(f"  Profile written to {profile_path}")
            if stdout and stdout.strip():
                output_lines = stdout.strip().split("\n")[:3]
                for line in output_lines:
                    print(f"    {line[:100]}")
                if len(stdout.strip().split("\n")) > 3:
                    print("    ...")

            return elapsed, returncode

        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            elapsed = time.perf_counter() - start_time
            print(f"  Command timed out after {elapsed:.3f}s: {' '.join(command_to_run)}")
            print(f"  Timeout was set to {timeout}s")
            if stdout and stdout.strip():
                print("  Stdout before timeout:")
                for line in stdout.strip().split("\n")[-10:]:
                    print(f"    {line}")
            if stderr and stderr.strip():
                print("  Stderr before timeout:")
                for line in stderr.strip().split("\n")[-5:]:
                    print(f"    {line}")
            raise

    def setup_requirements(self):
        """Download and prepare requirements.txt."""
        print("Setting up requirements.txt...")
        requirements_path = self.benchmark_dir / "requirements.txt"

        if requirements_path.exists() and not self.force_setup:
            print(f"Reusing existing {requirements_path}")
            return

        try:
            with urllib.request.urlopen(self.requirements_url) as response:
                content = response.read().decode("utf-8")

            # Filter out --index-url lines like the original.
            filtered_lines = [
                line
                for line in content.splitlines()
                if not line.strip().startswith("--index-url")
            ]

            with open(requirements_path, "w") as f:
                f.write("\n".join(filtered_lines))

            print(f"Downloaded {len(filtered_lines)} requirements")

        except Exception as e:
            print(f"Failed to download requirements: {e}")
            raise

    def clean_cache(self):
        """Clean pipenv and pip caches."""
        print("Cleaning caches...")
        cache_dirs = [Path.home() / ".cache" / "pip", Path.home() / ".cache" / "pipenv"]

        for cache_dir in cache_dirs:
            if cache_dir.exists():
                shutil.rmtree(cache_dir, ignore_errors=True)

    def clean_venv(self):
        """Clean virtual environment."""
        print("Cleaning virtual environment...")
        try:
            result = subprocess.run(
                ["pipenv", "--venv"],
                cwd=self.benchmark_dir,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
                env=subprocess_env(),
            )
            if result.returncode == 0:
                venv_path = Path(result.stdout.strip())
                if venv_path.exists():
                    print(f"  Removing venv: {venv_path}")
                    shutil.rmtree(venv_path, ignore_errors=True)
            else:
                print("  No virtual environment found")
        except subprocess.TimeoutExpired:
            print("  Warning: pipenv --venv timed out")
        except Exception as e:
            print(f"  Warning: Could not clean venv: {e}")

    def clean_lock(self):
        """Remove Pipfile.lock."""
        print("Cleaning lock file...")
        lock_file = self.benchmark_dir / "Pipfile.lock"
        if lock_file.exists():
            lock_file.unlink()

    def benchmark_tooling(self):
        """Benchmark pipenv installation using the current development version."""
        print("Benchmarking tooling...")
        parent_dir = self.benchmark_dir.parent
        elapsed, _ = self.run_timed_command(
            [sys.executable, "-m", "pip", "install", "-e", str(parent_dir)], "tooling.txt"
        )
        print(f"Tooling completed in {elapsed:.3f}s")

    def benchmark_import(self):
        """Benchmark importing requirements.txt to Pipfile."""
        print("Benchmarking import...")
        elapsed, _ = self.run_timed_command(
            ["pipenv", "install", "-r", "requirements.txt"], "import.txt"
        )
        print(f"Import completed in {elapsed:.3f}s")

    def benchmark_lock(self, timing_file: str):
        """Benchmark lock file generation."""
        print(f"Benchmarking lock ({timing_file})...")
        elapsed, _ = self.run_timed_command(["pipenv", "lock"], timing_file)
        print(f"Lock completed in {elapsed:.3f}s")

    def benchmark_install(self, timing_file: str):
        """Benchmark package installation."""
        print(f"Benchmarking install ({timing_file})...")
        elapsed, _ = self.run_timed_command(["pipenv", "sync"], timing_file)
        print(f"Install completed in {elapsed:.3f}s")

    def benchmark_update(self, timing_file: str):
        """Benchmark package updates."""
        print(f"Benchmarking update ({timing_file})...")
        elapsed, _ = self.run_timed_command(
            ["pipenv", "update"], timing_file, timeout=900
        )
        print(f"Update completed in {elapsed:.3f}s")

    def benchmark_add_package(self):
        """Benchmark adding a new package."""
        print("Benchmarking add package...")
        elapsed, _ = self.run_timed_command(
            ["pipenv", "install", self.test_package], "add-package.txt"
        )
        print(f"Add package completed in {elapsed:.3f}s")

    def get_pipenv_version(self) -> str:
        """Get pipenv version."""
        try:
            result = subprocess.run(
                ["pipenv", "--version"],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
                env=subprocess_env(),
            )
            return result.stdout.split()[-1]
        except Exception:
            return "unknown"

    def generate_stats(self):
        """Generate CSV stats file."""
        print("Generating stats...")
        version = self.get_pipenv_version()
        timestamp = int(time.time())

        stats_file = self.benchmark_dir / "stats.csv"

        with open(stats_file, "w", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "tool",
                    "version",
                    "timestamp",
                    "stat",
                    "elapsed time",
                    "system",
                    "user",
                    "cpu percent",
                    "max rss",
                    "inputs",
                    "outputs",
                ]
            )

            for stat in TIMED_STATS:
                timing_file = self.timings_dir / f"{stat}.txt"
                if timing_file.exists():
                    with open(timing_file) as f:
                        timing_data = f.read().strip().split(",")
                    writer.writerow(["pipenv", version, timestamp, stat] + timing_data)

        print(f"Stats written to {stats_file}")

    def write_json_results(self):
        if not self.output_json:
            return

        payload = {
            "tool": "pipenv",
            "version": self.get_pipenv_version(),
            "generated_at": int(time.time()),
            "records": [asdict(record) for record in self.records],
        }
        with open(self.output_json, "w") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        print(f"JSON results written to {self.output_json}")

    def run_operation(self, operation: str):
        if operation == "setup":
            self.setup_requirements()
        elif operation == "tooling":
            self.benchmark_tooling()
        elif operation == "import":
            self.benchmark_import()
        elif operation == "lock-cold":
            self.clean_cache()
            self.clean_venv()
            self.clean_lock()
            self.benchmark_lock("lock-cold.txt")
        elif operation == "lock-warm":
            self.clean_lock()
            self.benchmark_lock("lock-warm.txt")
        elif operation == "install-cold":
            self.clean_cache()
            self.clean_venv()
            self.benchmark_install("install-cold.txt")
        elif operation == "install-warm":
            self.clean_venv()
            self.benchmark_install("install-warm.txt")
        elif operation == "update-cold":
            self.clean_cache()
            self.benchmark_update("update-cold.txt")
        elif operation == "update-warm":
            self.benchmark_update("update-warm.txt")
        elif operation == "add-package":
            self.benchmark_add_package()
        elif operation == "stats":
            self.generate_stats()
        else:
            raise ValueError(f"Unknown operation: {operation}")

    def run_full_benchmark(self):
        """Run the complete benchmark suite."""
        print("=" * 60)
        print("Starting pipenv benchmark suite...")
        print("=" * 60)

        steps = [
            ("Setup", "setup"),
            ("Tooling", "tooling"),
            ("Import", "import"),
            ("Lock (cold)", "lock-cold"),
            ("Lock (warm)", "lock-warm"),
            ("Install (cold)", "install-cold"),
            ("Install (warm)", "install-warm"),
            ("Update (cold)", "update-cold"),
            ("Update (warm)", "update-warm"),
            ("Add package", "add-package"),
            ("Generate stats", "stats"),
        ]

        for index, (label, operation) in enumerate(steps, start=1):
            print(f"\n[{index}/{len(steps)}] {label}")
            print("-" * 40)
            self.run_operation(operation)

        print("\n" + "=" * 60)
        print("Benchmark suite completed!")
        print("=" * 60)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run pipenv package-manager benchmarks.")
    parser.add_argument(
        "operation",
        nargs="?",
        default="all",
        choices=("all", *OPERATIONS),
        help="Benchmark operation to run. Defaults to the full suite.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat the selected operation or full suite and store median timings.",
    )
    parser.add_argument(
        "--profile",
        action="store_true",
        help=(
            "Capture cProfile files in timings/. For pipenv commands, "
            "resolver work is kept in-process."
        ),
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=Path("benchmark-results.json"),
        help="Write per-run timing records to this JSON file.",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="Do not write benchmark-results.json.",
    )
    parser.add_argument(
        "--force-setup",
        action="store_true",
        help="Download requirements.txt even when a local copy already exists.",
    )
    args = parser.parse_args(argv)
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")
    return args


def main(argv=None):
    args = parse_args(argv)
    benchmark_dir = Path(__file__).parent
    output_json = None if args.no_json else benchmark_dir / args.output_json
    benchmark = PipenvBenchmark(
        benchmark_dir,
        profile=args.profile,
        output_json=output_json,
        force_setup=args.force_setup,
    )

    for iteration in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\nBenchmark iteration {iteration}/{args.repeat}")
        if args.operation == "all":
            benchmark.run_full_benchmark()
        else:
            benchmark.run_operation(args.operation)

    if args.operation not in {"all", "stats"}:
        benchmark.generate_stats()
    if args.operation != "stats":
        benchmark.write_json_results()


if __name__ == "__main__":
    main()
