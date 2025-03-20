#!/usr/bin/env python
from __future__ import annotations

import os
import sys
from pathlib import Path

from .pythonfinder import Finder


def main():
    """
    Test the Finder class.
    """
    print("Testing pythonfinder...")
    
    # Create a finder
    finder = Finder(system=True, global_search=True)
    
    # Find all Python versions
    print("\nAll Python versions:")
    all_versions = finder.find_all_python_versions()
    for version in all_versions:
        print(f"  {version.path} - {version.version_str} ({version.company})")
    
    # Find a specific Python version
    print("\nFinding Python 3:")
    python3 = finder.find_python_version(3)
    if python3:
        print(f"  Found Python 3: {python3.path} - {python3.version_str}")
    else:
        print("  Python 3 not found")
    
    # Find the python executable
    print("\nFinding 'python' executable:")
    python_path = finder.which("python")
    if python_path:
        print(f"  Found python: {python_path}")
    else:
        print("  Python executable not found")
    
    # On Windows, test the registry finder
    if os.name == "nt":
        print("\nWindows registry Python versions:")
        from .finders import WindowsRegistryFinder
        registry_finder = WindowsRegistryFinder()
        registry_versions = registry_finder.find_all_python_versions()
        for version in registry_versions:
            print(f"  {version.path} - {version.version_str} ({version.company})")


if __name__ == "__main__":
    main()
