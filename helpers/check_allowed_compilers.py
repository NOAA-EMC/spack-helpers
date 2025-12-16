"""Check that only specified compilers appear in a Spack environment.

This module provides functionality to validate that only whitelisted compilers
are used in a concretized Spack environment.
"""

from typing import List

import spack.spec


def _expand_compiler_synonyms(compiler_specs):
    """Expand compiler name synonyms to their full package names.
    
    Supports:
    - 'oneapi' -> 'intel-oneapi-compilers'
    - 'intel' -> 'intel-oneapi-compilers-classic'
    
    Args:
        compiler_specs: List of compiler spec strings
        
    Returns:
        List of compiler spec strings with synonyms expanded
    """
    synonyms = {
        'oneapi': 'intel-oneapi-compilers',
        'intel': 'intel-oneapi-compilers-classic'
    }
    
    expanded_specs = []
    for spec_str in compiler_specs:
        # Parse to extract compiler name
        spec = spack.spec.Spec(spec_str)
        base_name = spec.name
        
        # Replace if it's a synonym
        if base_name in synonyms:
            # Reconstruct spec string with full name
            full_name = synonyms[base_name]
            expanded_str = spec_str.replace(base_name, full_name, 1)
            expanded_specs.append(expanded_str)
        else:
            expanded_specs.append(spec_str)
    
    return expanded_specs


def check_allowed_compilers(env, allowed_compilers):
    """Check for specs using compilers not in the allowed list.
    
    Iterates over all concretized specs in the environment and identifies
    specs that use compilers (c, c++, fortran) not in the allowed list.
    
    Supports compiler name synonyms:
    - 'oneapi' -> 'intel-oneapi-compilers'
    - 'intel' -> 'intel-oneapi-compilers-classic'
    
    Args:
        env: A Spack Environment object to check
        allowed_compilers: List of allowed compiler specs (e.g., 'gcc@11.2.0', 'clang@14.0.0')
        
    Returns:
        List[Spec]: List of Spec objects that use disallowed compilers.
    """
    import spack.spec
    
    illegal_specs = []
    
    # Expand synonyms
    expanded_compilers = _expand_compiler_synonyms(allowed_compilers)
    
    # Parse allowed compiler specs
    allowed_compiler_specs = [spack.spec.Spec(spec_str) for spec_str in expanded_compilers]
    
    # Iterate over all concretized specs in the environment
    for user_spec, concrete_spec in env.concretized_specs():
        # Check c, c++, and fortran compilers
        for lang in ("c", "cxx", "fortran"):
            if lang in concrete_spec:
                compiler_spec = concrete_spec[lang]
                
                # Check if this compiler satisfies any of the allowed compiler specs
                is_allowed = any(
                    compiler_spec.satisfies(allowed_spec)
                    for allowed_spec in allowed_compiler_specs
                )
                
                # If this compiler is not allowed, mark as problematic
                if not is_allowed:
                    illegal_specs.append(concrete_spec)
                    break  # Only add each spec once
    
    return illegal_specs
