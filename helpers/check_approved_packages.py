"""Check that only approved packages appear in a Spack environment.

This module provides functionality to validate that only whitelisted packages
are present in a concretized Spack environment.
"""

from typing import List

import spack.spec
try:
    from spack.util import tty
except ImportError:
    try:
        from spack.llnl.util import tty
    except ImportError:
        from llnl.util import tty
from spack.error import SpackError


def read_approved_packages_from_file(filepath):
    """Read approved package names from a file.
    
    Args:
        filepath: Path to the file containing approved package names
        
    Returns:
        List[str]: List of approved package names
        
    Raises:
        SpackError: If the file cannot be read
    """
    try:
        with open(filepath, 'r') as f:
            approved_packages = [
                line.strip() for line in f
                if line.strip() and not line.strip().startswith('#')
            ]
        return approved_packages
    except IOError as e:
        raise SpackError(f"Could not read package list from {filepath}: {e}")


def check_approved_packages(env, approved_packages, only_roots=False):
    """Check for specs with package names not in the approved list.
    
    Iterates over all specs in the environment (including dependencies) and
    identifies specs whose package names are not in the approved list.
    External packages are excluded from this check.
    
    Args:
        env: A Spack Environment object to check
        approved_packages: List of approved package names (e.g., ['gcc', 'openmpi', 'hdf5'])
        only_roots: Only check env roots (default is check all specs)
        
    Returns:
        List[Spec]: List of Spec objects for unauthorized packages.
    """
    unauthorized_specs = []
    
    # Convert approved_packages to a set for faster lookup
    approved_set = set(approved_packages)

    if only_roots:
       specs = env.roots()
    else:
       specs = env.all_specs()

    # Iterate over all specs in the environment (including dependencies)
    for spec in specs:
        # Skip external packages
        if spec.external:
            tty.debug(f"Skipping external package: {spec.name}")
            continue
        
        pkg_name = spec.name
        
        # If this package is not approved, mark as unauthorized
        if pkg_name not in approved_set:
            unauthorized_specs.append(spec)
            if only_roots:
                concrete_msg = ["non-concrete", "concrete"][spec.concrete]
            else:
                concrete_msg = ["concrete"]
            tty.debug(f"Illegal {concrete_msg} package: {pkg_name} ({spec.__str__()})")
        else:
            tty.debug(f"Legal package validated: {pkg_name}")
    
    return unauthorized_specs
