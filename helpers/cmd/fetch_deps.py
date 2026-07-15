"""Fetch dependencies for packages in various languages.

This command fetches dependencies for packages that use different language
package managers (Go, Cargo, etc.) and caches them for offline installation.
"""

import os

try:
    from spack.util import tty
except ImportError:
    try:
        from spack.llnl.util import tty
    except ImportError:
        from llnl.util import tty

import spack.cmd
import spack.environment as ev
from spack.error import SpackError
from spack.extensions.helpers.fetch_go import fetch_go_dependencies
from spack.extensions.helpers.fetch_cargo import fetch_cargo_dependencies

description = "fetch dependencies for packages in various languages"
section = "build"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for fetch-deps command."""
    sp = subparser.add_subparsers(metavar='SUBCOMMAND', dest='deps_command')
    
    # Go subcommand
    go_parser = sp.add_parser(
        'go',
        help='fetch Go module dependencies'
    )
    go_parser.add_argument(
        'specs',
        nargs='*',
        help='specs to fetch dependencies for (default: all specs with go dependency in environment)'
    )
    go_parser.add_argument(
        '--use-spack-go',
        action='store_true',
        help='install and use go from Spack instead of system PATH'
    )
    
    # Cargo/Rust subcommand
    cargo_parser = sp.add_parser(
        'rust',
        help='fetch Rust/Cargo dependencies'
    )
    cargo_parser.add_argument(
        'specs',
        nargs='*',
        help='specs to fetch dependencies for (default: all specs with rust dependency in environment)'
    )
    cargo_parser.add_argument(
        '--use-spack-rust',
        action='store_true',
        help='install and use rust from Spack instead of system PATH'
    )


def fetch_deps(parser, args):
    """Handle fetch subcommands for go and cargo/rust.
    
    Args:
        parser: Arg parser
        args: Parsed command-line arguments    
    Returns:
        Exit code: 0 for success, 1 for errors
    """

    if not args.deps_command:
        parser.print_help()
        return 1
    
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")

    # Language-specific configuration
    if args.deps_command == 'go':
        env_var_name = 'GOMODCACHE'
        use_spack_flag = args.use_spack_go
    elif args.deps_command == 'rust':
        env_var_name = 'CARGO_HOME'
        use_spack_flag = args.use_spack_rust
    
    # Check required environment variable
    env_var_value = os.getenv(env_var_name)
    if not env_var_value:
        tty.warn(f"{env_var_name} environment variable not set.")

    # Get specs to process
    all_concrete = [s for s in env.all_specs() if s.concrete]
    if args.specs:
        specs = [s for s in all_concrete if any(s.satisfies(abstract_spec) for abstract_spec in args.specs)]
        for abstract_spec in args.specs:
            if all(not s.satisfies(abstract_spec) for s in all_concrete):
                tty.warn(f"No concretized specs could be found matching '{abstract_spec}'")
    else:
        specs = [s for s in all_concrete if args.deps_command in s]
    
    if not specs:
        tty.warn("No specs found to process")
        return 0
    
    try:
        if args.deps_command == 'go':
            fetch_go_dependencies(specs, use_spack_go=use_spack_flag)
        elif args.deps_command == 'rust':
            fetch_cargo_dependencies(specs, use_spack_rust=use_spack_flag)
        return 0
    except Exception as e:
        tty.error(f"Failed to fetch {args.deps_command} dependencies: {e}")
        return 1
