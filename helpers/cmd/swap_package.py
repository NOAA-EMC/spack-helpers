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
import spack.cmd.uninstall as uninstall_cmd
import spack.config
import spack.environment as ev
import spack.spec
import spack.store
from spack.enums import InstallRecordStatus
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
    subparser.add_argument(
        "--readd-removed-dependents",
        action="store_true",
        help="re-add removed dependents to the environment by package name only"
    )
    subparser.add_argument(
        "--dependent-spec",
        action="append",
        default=[],
        metavar="SPEC",
        help="explicit dependent spec to add back (repeatable, supports versions/variants)"
    )
    subparser.add_argument(
        "--uninstall-removed",
        action="store_true",
        help="uninstall installed specs corresponding to removed package roots"
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


def _add_root_specs(env, spec_strings):
    """Add root specs and return added spec strings."""
    added = []
    for spec_str in spec_strings:
        if env.add(spec_str):
            added.append(spec_str)
    return added


def _find_installed_specs_for_package_names(env, package_names):
    """Return installed specs in the active environment for package names."""
    hashes = env.all_hashes()
    installed = []
    seen_hashes = set()

    for pkg_name in sorted(package_names):
        matches = spack.store.STORE.db.query_local(
            spack.spec.Spec(pkg_name),
            hashes=hashes,
            installed=(InstallRecordStatus.INSTALLED | InstallRecordStatus.DEPRECATED),
        )
        for spec in matches:
            dag_hash = spec.dag_hash()
            if dag_hash in seen_hashes:
                continue
            seen_hashes.add(dag_hash)
            installed.append(spec)

    return installed


def _uninstall_installed_packages_by_name(env, package_names):
    """Uninstall installed specs matching package names in the active environment."""
    specs_to_uninstall = _find_installed_specs_for_package_names(env, package_names)
    if not specs_to_uninstall:
        return []

    uninstall_cmd.do_uninstall(specs_to_uninstall, force=False)
    return specs_to_uninstall


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

    existing_root_names = {spec.name for spec in env.user_specs}
    selected_missing_from_roots = selected_pkg_name not in existing_root_names
    if selected_missing_from_roots:
        tty.warn(
            f"Selected package '{selected_pkg_name}' is not a root in the active environment; "
            "adding it as a root spec."
        )

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
    remove_package_names.intersection_update(existing_root_names)

    # Possible transitive dependents (equivalent to: spack dependents -t <pkg_name>)
    allowed_buildable_names = _compute_possible_transitive_dependents(selected_pkg_name)

    explicit_dependent_specs = spack.cmd.parse_specs(args.dependent_spec) if args.dependent_spec else []
    explicit_dependent_names = {spec.name for spec in explicit_dependent_specs if spec.name}
    allowed_buildable_names.update(explicit_dependent_names)

    name_only_readd_specs = []
    if args.readd_removed_dependents:
        removed_dep_names = {spec.name for spec in installed_dependents}
        name_only_readd_specs = sorted(removed_dep_names - explicit_dependent_names)

    with env.write_transaction():
        removed = _remove_matching_roots(env, remove_package_names)
        added_selected = _add_root_specs(env, [args.package_spec]) if selected_missing_from_roots else []
        added_explicit = _add_root_specs(env, [str(spec) for spec in explicit_dependent_specs])
        added_name_only = _add_root_specs(env, name_only_readd_specs)
        _set_buildability_for_allowed_packages(env, allowed_buildable_names)

        tty.msg(
            f"Removed {len(removed)} root package(s) from environment: "
            + (", ".join(removed) if removed else "none")
        )
        tty.msg(
            f"Configured buildability for {len(allowed_buildable_names)} package(s): "
            "set packages:all:buildable:false and enabled selected dependent closure."
        )
        if added_selected or added_explicit or added_name_only:
            tty.msg(
                f"Added {len(added_selected) + len(added_explicit) + len(added_name_only)} root spec(s): "
                + ", ".join(added_selected + added_explicit + added_name_only)
            )

        if args.uninstall_removed and removed:
            uninstalled_specs = _uninstall_installed_packages_by_name(env, removed)
            tty.msg(
                f"Uninstalled {len(uninstalled_specs)} installed spec(s) for removed package names."
            )

        if args.fresh:
            tty.msg("Running fresh concretization...")
            with spack.config.override("concretizer:reuse", False):
                env.concretize()

        env.write()

    return 0