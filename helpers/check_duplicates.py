"""Check for duplicate package installations in a Spack environment.

This module provides functionality to detect when multiple hashes exist
for the same package name in a concretized Spack environment.
"""

from collections import defaultdict
from typing import Dict, List, Set

import spack.spec
try:
    from spack.util import tty
except ImportError:
    try:
        from spack.llnl.util import tty
    except ImportError:
        from llnl.util import tty


def _get_build_only_packages(env) -> Set[str]:
    """Identify packages that are only used as build dependencies.
    
    Args:
        env: A Spack Environment object to check
        
    Returns:
        Set[str]: Set of package names that only appear as build dependencies
    """
    all_packages = set()
    non_build_packages = set()
    
    # Traverse all specs and their dependencies
    for _, concrete_spec in env.concretized_specs():
        # Add root spec (always non-build)
        all_packages.add(concrete_spec.name)
        non_build_packages.add(concrete_spec.name)
        
        # Check all dependencies
        for dep in concrete_spec.traverse(root=False):
            dep_name = dep.name
            all_packages.add(dep_name)
            
            # Get the dependency relationship
            edges = concrete_spec.edges_to_dependencies(name=dep_name)
            for edge in edges:
                # If any edge is not build-only, mark as non-build
                if edge.depflag and not edge.depflag == spack.spec.dt.BUILD:
                    non_build_packages.add(dep_name)
                    break
    
    # Build-only packages are those in all_packages but not in non_build_packages
    return all_packages - non_build_packages


def check_duplicate_packages(env, ignore_packages=None, ignore_build_deps=False):
    """Check for duplicate package installations in a Spack environment.
    
    Iterates over all concretized specs in the environment and identifies
    packages that have multiple hashes (i.e., multiple installations).
    
    Args:
        env: A Spack Environment object to check
        ignore_packages: List of package names to exclude from duplicate checking
        ignore_build_deps: If True, ignore duplicates for packages that are only
                          used as build dependencies
        
    Returns:
        Dict[str, List[Spec]]: Dictionary with package names as keys and lists
                               of duplicate Spec objects as values. Only includes
                               packages with duplicates (length > 1).
    """
    if ignore_packages is None:
        ignore_packages = []
    
    # Build set of packages to ignore
    ignore_set = set(ignore_packages)
    
    # If ignore_build_deps is True, add build-only packages to ignore set
    if ignore_build_deps:
        build_only_packages = _get_build_only_packages(env)
        ignore_set.update(build_only_packages)
    
    # Track specs by package name
    packages_by_name = defaultdict(list)
    
    # Get all concretized specs from the environment
    for spec in env.all_specs():
        pkg_name = spec.name
        
        # Skip ignored packages
        if pkg_name in ignore_set:
            continue
        
        # Check if we already have a different hash for this package
        existing_hashes = [s.dag_hash() for s in packages_by_name[pkg_name]]
        if spec.dag_hash() not in existing_hashes:
            packages_by_name[pkg_name].append(spec)
    
    # Filter to only return packages with duplicates
    duplicates = {
        pkg_name: specs 
        for pkg_name, specs in packages_by_name.items() 
        if len(specs) > 1
    }
    
    return duplicates
