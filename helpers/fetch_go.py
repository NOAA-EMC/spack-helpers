"""Fetch Go module dependencies for Go dependents.

This module provides functionality to fetch Go module dependencies
and cache them in GOMODCACHE for offline installation.
"""

import os
from typing import Dict, List, Tuple

try:
    from spack.util import tty
except ImportError:
    try:
        from spack.llnl.util import tty
    except ImportError:
        from llnl.util import tty

try:
    from spack.util.filesystem import working_dir
except ImportError:
    from spack.llnl.util.filesystem import working_dir

import spack.spec
from spack.error import SpackError
from spack.installer import PackageInstaller
from spack.util.executable import Executable, which


def fetch_go_dependencies(specs: List["spack.spec.Spec"], use_spack_go: bool = False) -> None:
    """Fetch Go module dependencies for the given specs.
    
    This function processes a list of specs and fetches Go module dependencies
    for any spec that has 'go' as a direct dependency. The dependencies are 
    downloaded using 'go mod download'.
    
    Args:
        specs: List of concrete Spack specs to process
        use_spack_go: If True, install and use go from Spack instead of system PATH
    
    Raises:
        SpackError: If any fetch operation fails
    """

    if not os.getenv("GOMODCACHE"):
        tty.warn("GOMODCACHE is not set. Go dependents will be cached to their default location.")
    
    for spec in specs:
        if not spec.concrete:
            continue
        
        tty.msg(f"Fetching Go dependencies for: {spec.name}@{spec.version}/{spec.dag_hash()[:7]}")
        
        # Stage the package to get its source code
        pkg = spec.package
        pkg.do_stage()
        
        # Find the Go executable
        go_exe = _find_go_executable(spec, use_spack_go=use_spack_go)
        
        # Download dependencies using 'go mod download'
        with working_dir(pkg.stage.source_path):
            go_exe("mod", "download")
        
        tty.msg(f"  ✓ Fetched dependencies for {spec.name}")


def _find_go_executable(spec: "spack.spec.Spec", use_spack_go: bool = False) -> Executable:
    """Find the Go executable for the given spec.
    
    Attempts to find the Go executable in the following order:
    1. From the spec's 'go' dependency (if it exists and is installed)
    2. If use_spack_go is True, install go from Spack and use it
    3. From the system PATH (only if use_spack_go is False)
    
    Args:
        spec: The spec that may have a 'go' dependency
        use_spack_go: If True, install and use go from Spack instead of system PATH
    
    Returns:
        An Executable object for the go command
    
    Raises:
        SpackError: If no Go executable can be found
    """
    # Try to use the Go from the spec's dependency first
    go_dep = spec["go"]
    dep_go_path = os.path.join(go_dep.prefix.bin, "go")
        
    if which(dep_go_path):
        tty.debug(f"Using Go from spec dependency: {dep_go_path}")
        return Executable(dep_go_path)
    
    # If use_spack_go is requested, install go from Spack
    if use_spack_go:
        tty.msg("Installing 'go' from Spack...")
        installer = PackageInstaller([go_dep.package])
        installer.install()
        go_path = os.path.join(go_dep.prefix.bin, "go")
        if which(go_path):
            tty.info(f"Using Spack-installed Go: {go_path}")
            return Executable(go_path)
    
    # Fall back to system Go (only if use_spack_go is False)
    if not use_spack_go and which("go"):
        tty.debug("Using Go from system PATH")
        return Executable("go")
    
    raise SpackError(
        "Could not find 'go' executable.\n"
        "Either install the 'go' package as a dependency, use --use-spack-go, or ensure 'go' is in your PATH."
    )
