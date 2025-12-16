"""Configure Spack environment to allow only approved packages to be buildable.

This module provides functionality to mark approved packages as buildable
while setting all other packages as non-buildable in a Spack environment.
"""

import spack.llnl.util.tty as tty
from spack.error import SpackError


def read_approved_packages_from_file(filepath):
    """Read approved package names from a file.
    
    Args:
        filepath: Path to the file containing package names (one per line)
        
    Returns:
        List of approved package names
        
    Raises:
        SpackError: If file cannot be read
    """
    try:
        with open(filepath, 'r') as f:
            return [
                line.strip() for line in f 
                if line.strip() and not line.strip().startswith('#')
            ]
    except IOError as e:
        raise SpackError(f"Could not read package list from {filepath}: {e}")


def allow_only_approved_packages(env, approved_packages):
    """Configure environment to allow only approved packages to be buildable.
    
    Sets approved packages to buildable:true and all other packages to
    buildable:false in the environment's packages configuration.
    
    Args:
        env: Active Spack environment
        approved_packages: List of approved package names
        
    Returns:
        Number of packages configured as buildable
        
    Raises:
        SpackError: If no approved packages provided
    """
    if not approved_packages:
        raise SpackError("No approved packages specified.")
    
    # Get packages config from environment
    if 'packages' not in env.manifest.configuration:
        env.manifest.configuration['packages'] = {}
    
    packages = env.manifest.configuration['packages']
    
    # Process approved packages
    configured_count = 0
    for pkg_name in approved_packages:
        if pkg_name not in packages:
            packages[pkg_name] = {}
        
        # Check if already marked as buildable: false
        if packages[pkg_name].get('buildable') is False:
            tty.debug(f"Package '{pkg_name}' is already buildable:false, skipping.")
        else:
            packages[pkg_name]['buildable'] = True
            tty.debug(f"Set '{pkg_name}' buildable:true")
            configured_count += 1
    
    # Set packages:all:buildable:false
    if 'all' not in packages:
        packages['all'] = {}
    packages['all']['buildable'] = False
    
    # Mark as changed and write
    env.manifest.changed = True
    env.write()
    
    return configured_count
