"""Swap package policy in an active Spack environment.

This command removes an installed package's dependents from the environment,
then rewrites package buildability so only the selected package and its
possible transitive dependents remain buildable.
"""

try:
    import spack.llnl.util.tty as tty
except ImportError:
    import llnl.util.tty as tty

import spack.cmd
import spack.cmd.dependents as dependents_cmd
import spack.config
import spack.environment as ev
import spack.spec
import spack.store
from spack.error import SpackError

description = "swap an environment to a selected package and its transitive dependents"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for swap-package command."""
    subparser.add_argument(
        "package_spec",
        help="package spec to swap to (e.g., hdf5@1.14.6)"
    )
    subparser.add_argument(
        "--fresh",
        action="store_true",
        help="run concretization after updates (equivalent to 'spack concretize --fresh')"
    )


def _compute_possible_transitive_dependents(pkg_name):
    """Return possible transitive dependents by package name.

    Uses the same package-level graph logic as `spack dependents --transitive`
    (non-installed query mode).
    """
    ideps = dependents_cmd.inverted_dependencies()
    possible = dependents_cmd.get_dependents(pkg_name, ideps, transitive=True)
    possible.add(pkg_name)
    return possible


def _set_buildability_for_allowed_packages(env, allowed_pkg_names):
    """Set packages:all:buildable:false and allow only selected package names."""
    if "packages" not in env.manifest.configuration:
        env.manifest.configuration["packages"] = {}

    packages_cfg = env.manifest.configuration["packages"]

    if "all" not in packages_cfg:
        packages_cfg["all"] = {}
    packages_cfg["all"]["buildable"] = False

    for name in sorted(allowed_pkg_names):
        if name not in packages_cfg:
            packages_cfg[name] = {}
        packages_cfg[name]["buildable"] = True

    env.manifest.changed = True


def _remove_matching_roots(env, package_names):
    """Best-effort removal of matching root specs from the active environment."""
    removed_names = []

    for pkg_name in sorted(package_names):
        query_spec = spack.spec.Spec(pkg_name)

        env.remove(query_spec, force=True)
        removed_names.append(pkg_name)

    return removed_names


def swap_package(parser, args):
    """Handle swap-package command."""
    env = ev.active_environment()
    if not env:
        raise SpackError("No active Spack environment.")

    parsed = spack.cmd.parse_specs([args.package_spec])
    if len(parsed) != 1:
        raise SpackError("Provide exactly one package spec.")

    selected_query = parsed[0]
    selected_pkg_name = selected_query.name
    if not selected_pkg_name:
        raise SpackError("Could not determine package name from the provided spec.")

    # Installed transitive dependents (equivalent to: spack dependents -t -i <spec>)
    installed_dependents = []
    try:
        selected_installed = spack.cmd.disambiguate_spec(selected_query, env)
        installed_dependents = list(
            spack.store.STORE.db.installed_relatives(
                selected_installed,
                "parents",
                transitive=True,
            )
        )
    except Exception as exc:
        tty.warn(
            f"Could not resolve installed spec for '{args.package_spec}': {exc}. "
            "Continuing with buildability updates."
        )

    remove_package_names = {selected_pkg_name}
    remove_package_names.update(spec.name for spec in installed_dependents)

    # Possible transitive dependents (equivalent to: spack dependents -t <pkg_name>)
    allowed_buildable_names = _compute_possible_transitive_dependents(selected_pkg_name)

    with env.write_transaction():
        removed = _remove_matching_roots(env, remove_package_names)
        _set_buildability_for_allowed_packages(env, allowed_buildable_names)

        tty.msg(
            f"Removed {len(removed)} root package(s) from environment: "
            + (", ".join(removed) if removed else "none")
        )
        tty.msg(
            f"Configured buildability for {len(allowed_buildable_names)} package(s): "
            "set packages:all:buildable:false and enabled selected dependent closure."
        )

        if args.fresh:
            tty.msg("Running fresh concretization...")
            with spack.config.override("concretizer:reuse", False):
                env.concretize()

        env.write()

    return 0