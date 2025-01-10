import cProfile
import functools
import os
import pstats
from datetime import datetime
from pstats import SortKey


def profile_method(output_dir="profiles"):
    """
    Decorator to profile pipenv method execution with focus on file reads.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            profile_name = f"{func.__name__}_{timestamp}"
            profile_path = os.path.join(output_dir, f"{profile_name}.prof")

            profiler = cProfile.Profile()
            profiler.enable()

            try:
                result = func(*args, **kwargs)
                return result
            finally:
                profiler.disable()

                # Save and analyze stats
                stats = pstats.Stats(profiler)
                stats.sort_stats(SortKey.CUMULATIVE)
                stats.dump_stats(profile_path)
                print(f"\nProfile saved to: {profile_path}")

                # Analyze file reads specifically
                print("\nAnalyzing file read operations:")
                print("-" * 50)

                # Get all entries involving file read operations
                read_stats = stats.stats
                for (file, line, name), (_, _, tt, _, callers) in read_stats.items():
                    if "read" in str(name):
                        # Print the call stack for this read operation
                        print(f"\nFile read at: {file}:{line}")
                        print(f"Function: {name}")
                        print(f"Time: {tt:.6f}s")
                        print("Called by:")
                        for caller in callers:
                            caller_file, caller_line, caller_name = caller
                            print(f"  {caller_name} in {caller_file}:{caller_line}")
                        print("-" * 30)

                # Print overall stats
                print("\nTop 20 overall calls:")
                stats.print_stats(20)

        return wrapper

    return decorator
