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


## Environment validation
> [!IMPORTANT]
> All of the following commands must be run in an active, concretized environment. Unconcretized root specs will not be accounted for.

### Duplicate checking: validate check-duplicates
To check a concretized environment for more than one concretized spec for a given package name and ignore duplicates for specific packages `foo` and `bar`:
```console
spack check-duplicates --ignore foo --ignore bar
```

### Allow specific packages for a given C/C++/Fortran compiler: validate allow-pkgs-for-compiler
To verify that only specific packages to be built for a given compiler:
```console
spack allow-pkgs-for-compiler gcc foo bar
```
will return an error message if any packages other than `foo` and `bar` are spec'd with `%gcc`.

### Ensure only approved packages will be installed: validate check-approved-pkgs
To verify that only packages explicitly approved by the user have been concretized:
```console
spack check-approved-pkgs --packages foo bar
```
or
```console
spack check-approved-pkgs --pkgs-from-file approved_list.txt
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
