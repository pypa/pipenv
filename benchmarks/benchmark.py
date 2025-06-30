#!/usr/bin/env python3
"""
Pipenv benchmark runner based on python-package-manager-shootout.
"""
import csv
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Tuple


class PipenvBenchmark:
    def __init__(self, benchmark_dir: Path):
        self.benchmark_dir = benchmark_dir
        self.timings_dir = benchmark_dir / "timings"
        self.timings_dir.mkdir(exist_ok=True)
        self.requirements_url = "https://raw.githubusercontent.com/getsentry/sentry/51281a6abd8ff4a93d2cebc04e1d5fc7aa9c4c11/requirements-base.txt"
        self.test_package = "goodconf"

    def run_timed_command(
        self, command: List[str], timing_file: str, cwd: Path = None
    ) -> Tuple[float, int]:
        """Run a command and measure execution time."""
        if cwd is None:
            cwd = self.benchmark_dir

        print(f"  Running: {' '.join(command)}", flush=True)
        start_time = time.time()
        try:
            result = subprocess.run(
                command, cwd=cwd, capture_output=True, text=True, check=True
            )
            elapsed = time.time() - start_time

            # Write timing info (simplified format for cross-platform compatibility)
            timing_path = self.timings_dir / timing_file
            with open(timing_path, "w") as f:
                f.write(
                    f"{elapsed:.3f},0,0,0,0,0,0\n"
                )  # elapsed,system,user,cpu%,maxrss,inputs,outputs

            print(f"  ✓ Completed in {elapsed:.3f}s")
            if result.stdout.strip():
                # Show first few lines of output
                output_lines = result.stdout.strip().split("\n")[:3]
                for line in output_lines:
                    print(f"    {line[:100]}")
                if len(result.stdout.strip().split("\n")) > 3:
                    print("    ...")

            return elapsed, result.returncode
        except subprocess.CalledProcessError as e:
            elapsed = time.time() - start_time
            print(f"  ✗ Command failed after {elapsed:.3f}s: {' '.join(command)}")
            print(f"  Return code: {e.returncode}")
            if e.stderr.strip():
                print("  Error output:")
                for line in e.stderr.strip().split("\n")[:5]:
                    print(f"    {line}")
            if e.stdout.strip():
                print("  Stdout:")
                for line in e.stdout.strip().split("\n")[:3]:
                    print(f"    {line}")
            raise

    def setup_requirements(self):
        """Download and prepare requirements.txt."""
        print("Setting up requirements.txt...")
        requirements_path = self.benchmark_dir / "requirements.txt"

        try:
            with urllib.request.urlopen(self.requirements_url) as response:
                content = response.read().decode("utf-8")

            # Filter out --index-url lines like the original
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
            # Get venv path
            result = subprocess.run(
                ["pipenv", "--venv"],
                cwd=self.benchmark_dir,
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0:
                venv_path = Path(result.stdout.strip())
                if venv_path.exists():
                    print(f"  Removing venv: {venv_path}")
                    shutil.rmtree(venv_path, ignore_errors=True)
            else:
                print("  No virtual environment found")
        except Exception as e:
            print(f"  Warning: Could not clean venv: {e}")
            pass  # Ignore errors if venv doesn't exist

    def clean_lock(self):
        """Remove Pipfile.lock."""
        print("Cleaning lock file...")
        lock_file = self.benchmark_dir / "Pipfile.lock"
        if lock_file.exists():
            lock_file.unlink()

    def benchmark_tooling(self):
        """Benchmark pipenv installation (using current dev version)."""
        print("Benchmarking tooling...")
        # Install current development version
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
        elapsed, _ = self.run_timed_command(["pipenv", "update"], timing_file)
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
                ["pipenv", "--version"], capture_output=True, text=True, check=True
            )
            # Extract version from "pipenv, version X.X.X"
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

            stats = [
                "tooling",
                "import",
                "lock-cold",
                "lock-warm",
                "install-cold",
                "install-warm",
                "update-cold",
                "update-warm",
                "add-package",
            ]

            for stat in stats:
                timing_file = self.timings_dir / f"{stat}.txt"
                if timing_file.exists():
                    with open(timing_file) as f:
                        timing_data = f.read().strip()
                    writer.writerow(["pipenv", version, timestamp, stat, timing_data])

        print(f"Stats written to {stats_file}")

    def run_full_benchmark(self):
        """Run the complete benchmark suite."""
        print("=" * 60)
        print("Starting pipenv benchmark suite...")
        print("=" * 60)

        steps = [
            ("Setup", "setup_requirements"),
            ("Tooling", "benchmark_tooling"),
            ("Import", "benchmark_import"),
            ("Lock (cold)", "lock_cold"),
            ("Lock (warm)", "lock_warm"),
            ("Install (cold)", "install_cold"),
            ("Install (warm)", "install_warm"),
            ("Update (cold)", "update_cold"),
            ("Update (warm)", "update_warm"),
            ("Add package", "benchmark_add_package"),
            ("Generate stats", "generate_stats"),
        ]

        for i, (step_name, _) in enumerate(steps, 1):
            print(f"\n[{i}/{len(steps)}] {step_name}")
            print("-" * 40)

        # Setup
        print(f"\n[1/{len(steps)}] Setup")
        print("-" * 40)
        self.setup_requirements()

        # Tooling
        print(f"\n[2/{len(steps)}] Tooling")
        print("-" * 40)
        self.benchmark_tooling()

        # Import
        print(f"\n[3/{len(steps)}] Import")
        print("-" * 40)
        self.benchmark_import()

        # Lock cold
        print(f"\n[4/{len(steps)}] Lock (cold)")
        print("-" * 40)
        self.clean_cache()
        self.clean_venv()
        self.clean_lock()
        self.benchmark_lock("lock-cold.txt")

        # Lock warm
        print(f"\n[5/{len(steps)}] Lock (warm)")
        print("-" * 40)
        self.clean_lock()
        self.benchmark_lock("lock-warm.txt")

        # Install cold
        print(f"\n[6/{len(steps)}] Install (cold)")
        print("-" * 40)
        self.clean_cache()
        self.clean_venv()
        self.benchmark_install("install-cold.txt")

        # Install warm
        print(f"\n[7/{len(steps)}] Install (warm)")
        print("-" * 40)
        self.clean_venv()
        self.benchmark_install("install-warm.txt")

        # Update cold
        print(f"\n[8/{len(steps)}] Update (cold)")
        print("-" * 40)
        self.clean_cache()
        self.benchmark_update("update-cold.txt")

        # Update warm
        print(f"\n[9/{len(steps)}] Update (warm)")
        print("-" * 40)
        self.benchmark_update("update-warm.txt")

        # Add package
        print(f"\n[10/{len(steps)}] Add package")
        print("-" * 40)
        self.benchmark_add_package()

        # Generate stats
        print(f"\n[11/{len(steps)}] Generate stats")
        print("-" * 40)
        self.generate_stats()

        print("\n" + "=" * 60)
        print("Benchmark suite completed!")
        print("=" * 60)


def main():
    benchmark_dir = Path(__file__).parent
    benchmark = PipenvBenchmark(benchmark_dir)

    if len(sys.argv) > 1:
        operation = sys.argv[1]
        if operation == "setup":
            benchmark.setup_requirements()
        elif operation == "tooling":
            benchmark.benchmark_tooling()
        elif operation == "import":
            benchmark.benchmark_import()
        elif operation == "lock-cold":
            benchmark.clean_cache()
            benchmark.clean_venv()
            benchmark.clean_lock()
            benchmark.benchmark_lock("lock-cold.txt")
        elif operation == "lock-warm":
            benchmark.clean_lock()
            benchmark.benchmark_lock("lock-warm.txt")
        elif operation == "install-cold":
            benchmark.clean_cache()
            benchmark.clean_venv()
            benchmark.benchmark_install("install-cold.txt")
        elif operation == "install-warm":
            benchmark.clean_venv()
            benchmark.benchmark_install("install-warm.txt")
        elif operation == "update-cold":
            benchmark.clean_cache()
            benchmark.benchmark_update("update-cold.txt")
        elif operation == "update-warm":
            benchmark.benchmark_update("update-warm.txt")
        elif operation == "add-package":
            benchmark.benchmark_add_package()
        elif operation == "stats":
            benchmark.generate_stats()
        else:
            print(f"Unknown operation: {operation}")
            sys.exit(1)
    else:
        benchmark.run_full_benchmark()


if __name__ == "__main__":
    main()
