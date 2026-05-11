# spack-helpers

[![pytest](https://github.com/NOAA-EMC/spack-helpers/actions/workflows/pytest.yml/badge.svg)](https://github.com/NOAA-EMC/spack-helpers/actions/workflows/pytest.yml)
[![Test custom action](https://github.com/NOAA-EMC/spack-helpers/actions/workflows/test-custom-action.yml/badge.svg)](https://github.com/NOAA-EMC/spack-helpers/actions/workflows/test-custom-action.yml)

This Spack extension provides useful commands for modifying and validating and filter Spack environments.


## Setup
To register the extension with Spack, activate a Spack instance (`$SPACK_ROOT` defined and `spack` executable available), then run:
```console
  . source_me.sh
```


## Compiler filtering: filter-compilers
The `filter-compilers` subcommand can be used to filter compilers inclusively or exclusively from Spack `packages` configuration to ensure unwanted compilers are not considered for use by the concretizer:

```console
  spack filter-compilers <compiler-specs> (--keep-only | --remove)
```

Example: keep only a single gcc version:
```console
  spack filter-compilers gcc@11.2.0 --keep-only
```

## Intel OneAPI configuration fixes: fix-intel-config
The `fix-intel-config` subcommand performs various fixes for Intel OneAPI external specs:

1. **Library path configuration**: Adds `LD_LIBRARY_PATH` modifications to external Intel Classic (intel-oneapi-compilers-classic) specs. Without this, some package installations may fail with libimf.so not being found.

2. **Compiler consolidation** (optional with `-c`/`--consolidate`): Consolidates intel-oneapi-compilers externals by version. Some Intel OneAPI installations have separate externals for C/C++ compilers (icx/icpx) and Fortran (ifx) with slightly different version numbers (e.g., 2025.3.1 vs 2025.3.0). The consolidation feature automatically merges these into a single external based on the first two version numbers.

Basic usage (applies library path fix only):
```console
  spack fix-intel-config
```

With compiler consolidation:
```console
  spack fix-intel-config --consolidate
```

Note: This should be run after detecting external Intel installations.


## Dependency fetching for Go- and Rust/Cargo-based packages: fetch-deps (go|rust)
The `fetch-deps` subcommand can be used to fetch dependencies for Go packages (defined in go.mod) or Rust/Cargo packages (defined in Cargo.toml). This command requires a concretized environment. It checks the environment for `go` or `rust` dependents, fetches their source code, and retrieves dependencies to `$GOMODCACHE`/`$CARGO_HOME` (or default location).

To fetch dependencies for all Go-based packages:
```console
spack fetch-deps go
```

To fetch dependencies for all Rust/Cargo-based packages and ensure that the spec'd `rust` dependency is used to do the fetching (this will install the `rust` package via Spack if it is not already present):
```console
spack fetch-deps rust --use-spack-rust
```


## Create Python virtual environments from Spack installs: create-python-venv
The `create-python-venv` command interactively creates a Python virtual environment and integrates selected Spack-installed Python packages.

```console
spack create-python-venv [venv-path]
```

Behavior:

1. If no Spack environment is active, it lists environments (equivalent to `spack env ls`) and prompts for one to activate.
2. It lists installed `python` specs in that environment and prompts for one selection (even if there is only one).
3. It lists installed packages whose build-system type is `PythonPackage` and allows selecting multiple entries.
4. It errors if the selection includes more than one spec with the same package name.
5. It optionally populates the new venv with `pip install` from one of: `requirements.txt` in current directory, `pyproject.toml` in current directory, a user-provided `requirements.txt`/`pyproject.toml` path, or a manually entered package list.
6. It creates the venv using the selected Python and writes a `.pth` integration file under the venv to include selected package paths.

After creation, activate with:
```console
source <venv-path>/bin/activate
```


## Swap package policy and roots: swap-package
The `swap-package` command updates an active environment around one selected package spec.

```console
spack swap-package <package-spec> [--fresh] [--readd-removed-dependents] [--dependent-spec <spec> ...] [--uninstall-removed]
```

Behavior:

1. Parses `<package-spec>` and determines the selected package name.
2. If the selected package is not already a root in the active environment, it warns and adds it as a root spec (equivalent to `spack add <package-spec>`).
3. Finds installed transitive dependents (equivalent to `spack dependents --transitive --installed <spec>`).
4. Removes matching root specs from the active environment for discovered installed dependents and selected package when present as roots (equivalent behavior to `spack remove <pkg-name>` on each).
5. Sets `packages:all:buildable:false` and enables `buildable:true` only for the selected package name and all possible transitive dependents from Spack's package graph.
6. Optionally runs concretization with fresh reuse policy (`concretizer:reuse=false`) when `--fresh` is provided.

Useful options:

1. `--readd-removed-dependents`: after removal, add discovered removed dependents back as root specs by package name only.
2. `--dependent-spec <spec>` (repeatable): add explicit dependent root specs with version/variant control, e.g. `--dependent-spec hdf5@1.14.0 --dependent-spec netcdf-c+mpi`.
  Explicit dependent specs take precedence over name-only re-adds.
3. `--uninstall-removed`: uninstall installed specs that correspond to removed package roots. This is off by default.


## Environment validation
> [!IMPORTANT]
> All of the following commands must be run in an active, concretized environment. Unconcretized root specs will not be accounted for.

### Duplicate checking: validate check-duplicates
To check a concretized environment for more than one concretized spec for a given package name and ignore duplicates for specific packages `foo` and `bar`:
```console
spack validate check-duplicates --ignore foo --ignore bar
```

### Allow specific packages for a given C/C++/Fortran compiler: validate allow-pkgs-for-compiler
To verify that only specific packages to be built for a given compiler:
```console
spack validate allow-pkgs-for-compiler gcc foo bar
```
will return an error message if any packages other than `foo` and `bar` are spec'd with `%gcc`.

### Ensure only approved packages will be installed: validate check-approved-pkgs
To verify that only packages explicitly approved by the user have been concretized:
```console
spack validate check-approved-pkgs --packages foo bar
```
or
```console
spack validate check-approved-pkgs --pkgs-from-file approved_list.txt
```
where `approved_list.txt` contains newline-delimited package names:
```
gmake
cmake
gcc
gcc-runtime
...
```

### Ensure only specific C/C++/Fortran compilers are used: validate compilers
To verify that only specific C/C++/Fortran compilers have been concretized:
```console
spack validate compilers intel-oneapi-compilers gcc
```
will return an error if any packages have `c`/`cxx`/`fortran` providers that are not `intel-oneapi-compilers` or `gcc`.

### Verify unbuildable packages are not being built: validate check-buildable
To verify that packages marked as `buildable:false` in the environment configuration are not being built (i.e., they use externals):
```console
spack validate check-buildable
```
will return an error if any packages are marked as `buildable:false` but are nonetheless being built.


## spack-stack deployment
To run a deploy based on a deployments.yaml for a given spack-stack directory and site, run
```console
spack deploy
```
Compared with the deploy.py utility in spack-stack, this will implement more robust checks. This copy and not the spack-stack one should be used for WCOSS2 installations.


## Python API
To access the extensions via Spack Python API (`spack-python` etc.), do, e.g.:
```python
spack.extensions.load_extension("helpers")
from spack.extensions.helpers import *
from spack.extensions.helpers.cmd import validate
```
after associating the extensions with your Spack instance (i.e., sourcing source_me.sh).


## Unit tests
To run the unit tests:
```console
spack unit-test --extension=helpers
```
See tests/README.md for more details.
