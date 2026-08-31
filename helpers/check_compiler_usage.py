"""Check compiler usage in a Spack environment.

This module provides functionality to validate that only specified packages
use a particular compiler in a concretized Spack environment.

Supports both old Spack (compilers.yaml) and new Spack (compilers-as-nodes).
"""

from typing import List

import spack.spec
from spack.extensions.helpers.compiler_compat import uses_compilers_as_nodes


def check_compiler_usage(env, restricted_compiler_name, allowed_packages):
    """Check for packages using a compiler that are not in the allowed list.
    
    Iterates over all concretized specs in the environment and identifies
    packages that use the specified compiler but are not in the allowed list.
    
    Supports both:
    - New Spack (compilers-as-nodes): Checks spec["c"], spec["cxx"], spec["fortran"]
    - Old Spack (compilers.yaml): Checks spec.compiler.name attribute
    
    Args:
        env: A Spack Environment object to check
        restricted_compiler_name: Name of the compiler to check (e.g., 'gcc', 'clang', 'intel')
        allowed_packages: List of package names allowed to use this compiler
        
    Returns:
        List[Spec]: List of Spec objects for packages that use the compiler
                    but are not in the allowed list.
    """
    illegal_specs = []
    
    # Convert allowed_packages to a set for faster lookup
    allowed_set = set(allowed_packages)
    
    # Iterate over all concretized specs in the environment
    for user_spec, concrete_spec in env.all_specs():
        pkg_name = concrete_spec.name

        if pkg_name in allowed_set:
            continue

        # Check if this spec uses the specified compiler
        uses_restricted_compiler = False
        
        if uses_compilers_as_nodes(concrete_spec):
            # New approach: check language-specific compilers
            for lang in ("c", "cxx", "fortran"):
                if lang in concrete_spec:
                    if concrete_spec[lang].name == restricted_compiler_name:
                        uses_restricted_compiler = True
                        break
        else:
            # Old approach: check spec.compiler.name
            if hasattr(concrete_spec, 'compiler') and concrete_spec.compiler:
                if concrete_spec.compiler.name == restricted_compiler_name:
                    uses_restricted_compiler = True
        
        if uses_restricted_compiler:
            illegal_specs.append(concrete_spec)
    
    return illegal_specs
