"""Fix Intel OneAPI configuration for external specs.

This module provides functionality to:
1. Add LD_LIBRARY_PATH configuration to intel-oneapi-compilers-classic external specs
2. Consolidate intel-oneapi-compilers externals by version
"""

import re
from collections import defaultdict

import spack.config
from spack.llnl.util import tty


def fix_intel_lib_config_for_env(env):
    """Add LD_LIBRARY_PATH configuration to intel-oneapi-compilers-classic externals.
    
    For each external spec in packages:intel-oneapi-compilers-classic:externals,
    this function adds:
        extra_attributes:
          environment:
            prepend_path:
              LD_LIBRARY_PATH: <prefix>/linux/compiler/lib/intel64_lin
    
    This function only modifies the environment's spack.yaml file. If an external
    is found in another configuration file, a new overriding entry is created
    in spack.yaml using the :: syntax.
    
    Args:
        env: Active Spack environment
        
    Returns:
        int: Number of external specs modified
    """
    PACKAGE_NAME = 'intel-oneapi-compilers-classic'
    LIB_PATH_SUFFIX = 'compiler/lib/intel64_lin'
    
    # Get all packages configuration (from all scopes to find externals)
    all_packages = spack.config.get('packages')
    
    if not all_packages:
        tty.debug("No packages configuration found")
        return 0
    
    # Check if the intel-oneapi-compilers-classic package exists
    if PACKAGE_NAME not in all_packages:
        tty.debug(f"Package {PACKAGE_NAME} not found in configuration")
        return 0
    
    pkg_config = all_packages[PACKAGE_NAME]
    
    # Skip if config is not a dict or has no 'externals' section
    if not isinstance(pkg_config, dict) or 'externals' not in pkg_config:
        tty.debug(f"No externals found for {PACKAGE_NAME}")
        return 0
    
    externals = pkg_config['externals']
    if not isinstance(externals, list):
        tty.debug(f"Externals is not a list for {PACKAGE_NAME}")
        return 0
    
    # Process each external and add the LD_LIBRARY_PATH configuration
    modified_externals = []
    modified_count = 0
    
    for external in externals:
        if not isinstance(external, dict) or 'spec' not in external or 'prefix' not in external:
            # Keep unmodified if it doesn't have the required fields
            modified_externals.append(external)
            continue
        
        # Create a copy of the external dict to modify
        modified_external = dict(external)
        
        # Construct the library path from the prefix
        prefix = external['prefix']
        lib_path = f"{prefix}/{LIB_PATH_SUFFIX}"
        
        # Check if extra_attributes already exists
        if 'extra_attributes' not in modified_external:
            modified_external['extra_attributes'] = {}
        
        extra_attrs = modified_external['extra_attributes']
        
        # Check if environment already exists
        if 'environment' not in extra_attrs:
            extra_attrs['environment'] = {}
        
        environment = extra_attrs['environment']
        
        # Check if prepend_path already exists
        if 'prepend_path' not in environment:
            environment['prepend_path'] = {}
        
        prepend_path = environment['prepend_path']
        
        # Check if LD_LIBRARY_PATH already exists
        if 'LD_LIBRARY_PATH' not in prepend_path:
            # Add the LD_LIBRARY_PATH
            prepend_path['LD_LIBRARY_PATH'] = lib_path
            modified_count += 1
            tty.debug(f"Added LD_LIBRARY_PATH={lib_path} for spec {external['spec']}")
        else:
            # Check if the path is already correct
            existing_path = prepend_path['LD_LIBRARY_PATH']
            if existing_path != lib_path:
                # Update the path
                prepend_path['LD_LIBRARY_PATH'] = lib_path
                modified_count += 1
                tty.debug(f"Updated LD_LIBRARY_PATH from {existing_path} to {lib_path} for spec {external['spec']}")
            else:
                tty.debug(f"LD_LIBRARY_PATH already correct for spec {external['spec']}")
        
        modified_externals.append(modified_external)
    
    # Write to environment configuration (spack.yaml) if anything was modified
    if modified_count > 0:
        # Get existing packages config ONLY from the environment's spack.yaml
        env_packages = env.manifest.configuration.get('packages', {})
        
        # Start with existing config for this package (if any)
        # This preserves require, compiler, variants, etc.
        new_pkg_config = dict(all_packages.get(PACKAGE_NAME, {}))
        
        # Replace externals section with modified one
        new_pkg_config['externals'] = modified_externals
        
        # Remove any existing entries for this package
        # (both with and without :: suffix to avoid duplicates)
        env_packages.pop(PACKAGE_NAME, None)
        env_packages.pop(f"{PACKAGE_NAME}:", None)
        
        # Write with :: syntax to override in environment
        env_packages[f"{PACKAGE_NAME}:"] = new_pkg_config
        
        # Update the environment's packages config
        env.manifest.configuration['packages'] = env_packages
        env.manifest.changed = True
    
    return modified_count


def consolidate_intel_oneapi_compilers(env):
    """Consolidate intel-oneapi-compilers externals by first two version numbers.
    
    This function identifies intel-oneapi-compilers externals where some only have
    ifx and others only have icx+icpx, and consolidates them based on matching
    the first two version numbers (e.g., 2025.3.0 and 2025.3.1 -> 2025.3).
    
    Args:
        env: Active Spack environment
        
    Returns:
        int: Number of external specs consolidated (merged pairs count)
    """
    PACKAGE_NAME = 'intel-oneapi-compilers'
    
    # Get all packages configuration
    all_packages = spack.config.get('packages')
    
    if not all_packages:
        tty.debug("No packages configuration found")
        return 0
    
    # Check if the intel-oneapi-compilers package exists
    if PACKAGE_NAME not in all_packages:
        tty.debug(f"Package {PACKAGE_NAME} not found in configuration")
        return 0
    
    pkg_config = all_packages[PACKAGE_NAME]
    
    # Skip if config is not a dict or has no 'externals' section
    if not isinstance(pkg_config, dict) or 'externals' not in pkg_config:
        tty.debug(f"No externals found for {PACKAGE_NAME}")
        return 0
    
    externals = pkg_config['externals']
    if not isinstance(externals, list):
        tty.debug(f"Externals is not a list for {PACKAGE_NAME}")
        return 0
    
    # Parse externals and categorize them
    # Key: (prefix_base, major.minor), Value: list of externals
    ifx_only = defaultdict(list)
    icx_only = defaultdict(list)
    complete = []  # Externals that have all compilers
    
    for external in externals:
        spec_str = external['spec']
        prefix = external['prefix']
        
        # Extract version from spec (format: "intel-oneapi-compilers@version languages=...")
        # or just "intel-oneapi-compilers@version"
        version_match = re.search(r'@([\d.]+)', spec_str)
        if not version_match:
            tty.debug(f"No version found in spec '{spec_str}', keeping as-is")
            complete.append(external)
            continue
        
        version = version_match.group(1)
        version_parts = version.split('.')
        
        if len(version_parts) < 2:
            tty.debug(f"Version '{version}' has fewer than 2 parts, keeping '{spec_str}' as-is")
            complete.append(external)
            continue
        
        # Get first two version numbers (e.g., "2025.3")
        version_key = f"{version_parts[0]}.{version_parts[1]}"
        
        # Determine which compilers are available by checking extra_attributes
        extra_attrs = external.get('extra_attributes', {})
        compilers = extra_attrs.get('compilers', {})
        
        if not compilers:
            tty.debug(f"No compilers defined in extra_attributes for '{spec_str}', treating as complete")
            complete.append(external)
            continue
        
        # Check which compilers are present
        has_fortran = 'fortran' in compilers
        has_c_or_cxx = 'c' in compilers or 'cxx' in compilers
        
        # Extract the prefix directory that's common (without the full version)
        # e.g., /opt/intel/oneapi/compilers/2025.3.1 -> /opt/intel/oneapi/compilers
        prefix_parts = prefix.rstrip('/').split('/')
        # Find where the version directory is
        version_idx = None
        for i, part in enumerate(prefix_parts):
            if version in part:
                version_idx = i
                break
        
        if version_idx is not None:
            prefix_base = '/'.join(prefix_parts[:version_idx])
        else:
            prefix_base = prefix
        
        key = (prefix_base, version_key)
        
        # Categorize based on available compilers
        # fortran-only: has fortran but not c/cxx
        # c/cxx-only: has c/cxx but not fortran
        if has_fortran and not has_c_or_cxx:
            tty.debug(f"Detected fortran-only external '{spec_str}' with version key {version_key}")
            ifx_only[key].append(external)
        elif has_c_or_cxx and not has_fortran:
            tty.debug(f"Detected c/cxx-only external '{spec_str}' with version key {version_key}")
            icx_only[key].append(external)
        else:
            # Has both or neither - keep as-is
            tty.debug(f"External '{spec_str}' has all languages or none, treating as complete")
            complete.append(external)
    
    # Now consolidate matching pairs
    consolidated_externals = []
    consolidated_count = 0
    used_keys = set()
    
    for key, ifx_externals in ifx_only.items():
        if key in used_keys:
            continue
        
        if key in icx_only:
            # We have a matching pair to consolidate
            icx_externals = icx_only[key]
            
            # Take the first of each (typically there should only be one per category)
            ifx_ext = ifx_externals[0]
            icx_ext = icx_externals[0]
            
            # Create consolidated external
            consolidated = _merge_externals(ifx_ext, icx_ext, key[1])
            consolidated_externals.append(consolidated)
            
            tty.debug(f"Consolidated {ifx_ext['spec']} and {icx_ext['spec']} into {consolidated['spec']}")
            consolidated_count += 1
            used_keys.add(key)
            
            # Add any additional externals beyond the first one back as-is
            for extra in ifx_externals[1:]:
                complete.append(extra)
            for extra in icx_externals[1:]:
                complete.append(extra)
        else:
            # No matching icx external, keep ifx ones as-is
            for ext in ifx_externals:
                complete.append(ext)
    
    # Add icx-only externals that weren't matched
    for key, icx_externals in icx_only.items():
        if key not in used_keys:
            for ext in icx_externals:
                complete.append(ext)
    
    # Combine all externals
    final_externals = consolidated_externals + complete
    
    # Write to environment configuration if anything was consolidated
    if consolidated_count > 0:
        # Get existing packages config from the environment
        env_packages = env.manifest.configuration.get('packages', {})
        
        # Start with existing config for this package
        new_pkg_config = dict(all_packages.get(PACKAGE_NAME, {}))
        
        # Replace externals section with consolidated one
        new_pkg_config['externals'] = final_externals
        
        # Remove any existing entries for this package
        env_packages.pop(PACKAGE_NAME, None)
        env_packages.pop(f"{PACKAGE_NAME}:", None)
        
        # Write with :: syntax to override in environment
        env_packages[f"{PACKAGE_NAME}:"] = new_pkg_config
        
        # Update the environment's packages config
        env.manifest.configuration['packages'] = env_packages
        env.manifest.changed = True
    
    return consolidated_count


def _merge_externals(ifx_ext, icx_ext, version_key):
    """Merge two externals (ifx-only and icx-only) into a single external.
    
    Preserves all properties from both externals, with icx_ext taking precedence
    for conflicting top-level properties (except spec and extra_attributes which
    are merged intelligently).
    
    Args:
        ifx_ext: External with ifx compiler
        icx_ext: External with icx/icpx compilers
        version_key: Version key to use (e.g., "2025.3")
        
    Returns:
        dict: Merged external configuration
    """
    # Start with all properties from ifx_ext
    merged = dict(ifx_ext)
    
    # Merge in all properties from icx_ext (except spec and extra_attributes)
    for key, value in icx_ext.items():
        if key not in ('spec', 'extra_attributes'):
            merged[key] = value
    
    # Create consolidated spec with all languages
    # Extract the base spec without languages from icx
    spec_str = icx_ext['spec']
    spec_base = spec_str.split('languages=')[0].strip()
    # Remove existing version from spec_base (e.g., "intel-oneapi-compilers@2025.3.1" -> "intel-oneapi-compilers")
    spec_base = re.sub(r'@[\d.]+', '', spec_base)
    merged['spec'] = f"{spec_base}@{version_key} languages=c,cxx,fortran"
    
    # Merge extra_attributes from both externals
    merged_attrs = {}
    
    # Start with ifx extra_attributes
    if 'extra_attributes' in ifx_ext:
        merged_attrs = _deep_merge_dict(merged_attrs, ifx_ext['extra_attributes'])
    
    # Merge in icx extra_attributes (takes precedence for conflicts)
    if 'extra_attributes' in icx_ext:
        merged_attrs = _deep_merge_dict(merged_attrs, icx_ext['extra_attributes'])
    
    if merged_attrs:
        merged['extra_attributes'] = merged_attrs
    
    return merged


def _deep_merge_dict(base, update):
    """Deep merge two dictionaries.
    
    Args:
        base: Base dictionary
        update: Dictionary to merge in
        
    Returns:
        dict: Merged dictionary
    """
    result = dict(base)
    
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge_dict(result[key], value)
        else:
            result[key] = value
    
    return result
