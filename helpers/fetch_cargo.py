"""Fetch Rust/Cargo dependencies for specs that depend on rust.

This module provides functionality to fetch Rust dependencies using cargo
and cache them in CARGO_HOME for offline installation.
"""

import os
from typing import Dict, List, Optional

try:
    import spack.llnl.util.tty as tty
    from spack.llnl.util.filesystem import working_dir
except ImportError:
    import llnl.util.tty as tty
    from llnl.util.filesystem import working_dir

import spack.spec
from spack.error import SpackError
from spack.installer import PackageInstaller
from spack.util.executable import Executable, which


def fetch_cargo_dependencies(
    specs: List["spack.spec.Spec"],
    use_spack_rust: bool = False
) -> None:
    """Fetch Cargo dependencies for the given specs.
    
    This function processes a list of specs and fetches Cargo dependencies
    for any spec that depends on 'rust' and has a Cargo.toml file. The
    dependencies are downloaded to the specified CARGO_HOME directory using
    'cargo fetch'.
    
    Args:
        specs: List of concrete Spack specs to process
        use_spack_rust: If True, install and use rust from Spack instead of system PATH
    
    """

    if not os.getenv("CARGO_HOME"):
        tty.warn("CARGO_HOME is not set. Rust/Cargo dependents will be cached to their default location.")

    for spec in specs:
        if not spec.concrete:
            continue
            
        # Stage the package to get its source code
        pkg = spec.package
        pkg.do_stage()
        
        # Check if Cargo.toml exists
        cargo_toml = os.path.join(pkg.stage.source_path, "Cargo.toml")
        if not os.path.isfile(cargo_toml):
            continue
        
        tty.msg(f"Fetching Cargo dependencies for: {spec.name}@{spec.version}/{spec.dag_hash()[:7]}")
        
        # Find the cargo executable
        cargo_exe = _find_cargo_executable(spec, use_spack_rust)
        
        # Download dependencies using 'cargo fetch'
        with working_dir(pkg.stage.source_path):
            cargo_exe("fetch")
        
        tty.msg(f"  ✓ Fetched dependencies for {spec.name}")


def _find_cargo_executable(
    spec: "spack.spec.Spec",
    use_spack_rust: bool = False
) -> Executable:
    """Find the Cargo executable for the given spec.
    
    Attempts to find the Cargo executable in the following order:
    1. From the spec's 'rust' dependency (if it exists and is installed)
    2. If use_spack_rust is True, install rust from Spack and use it
    3. From the system PATH (only if use_spack_rust is False)
    
    Args:
        spec: The spec that may have a 'rust' dependency
        use_spack_rust: If True, install and use rust from Spack instead of system PATH
    
    Returns:
        An Executable object for the cargo command
    
    Raises:
        SpackError: If no Cargo executable can be found
    """
    # Try to use the Cargo from the spec's rust dependency first
    rust_dep = spec["rust"]
    dep_cargo_path = os.path.join(rust_dep.prefix.bin, "cargo").replace("/bin/bin/", "/bin/")
        
    if which(dep_cargo_path):
        tty.debug(f"Using Cargo from spec dependency: {dep_cargo_path}")
        return Executable(dep_cargo_path)
    
    # If use_spack_rust is requested, install rust from Spack
    if use_spack_rust:
        tty.msg("Installing 'rust' from Spack...")
        installer = PackageInstaller([rust_dep.package])
        installer.install()
        cargo_path = os.path.join(rust_dep.prefix.bin, "cargo")
        if which(cargo_path):
            tty.info(f"Using Spack-installed Cargo: {cargo_path}")
            return Executable(cargo_path)
    
    # Fall back to system Cargo (only if use_spack_rust is False)
    if not use_spack_rust and which("cargo"):
        tty.debug("Using Cargo from system PATH")
        return Executable("cargo")
    
    raise SpackError(
        "Could not find 'cargo' executable.\n"
        "Either install the 'rust' package as a dependency, use --use-spack-rust, or ensure 'cargo' is in your PATH."
    )
