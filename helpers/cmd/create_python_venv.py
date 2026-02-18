"""Create a Python virtual environment from packages in a Spack environment."""

import os
import subprocess
from collections import Counter

try:
    import spack.llnl.util.tty as tty
except ImportError:
    import llnl.util.tty as tty

import spack.environment as ev
from spack.error import SpackError

description = "create a Python virtual environment from Spack-installed packages"
section = "environments"
level = "long"


def setup_parser(subparser):
    """Setup argument parser for create-python-venv command."""
    subparser.add_argument(
        "venv_path",
        nargs="?",
        default=".venv",
        help="target path for the virtual environment (default: .venv)",
    )


def _format_spec(spec):
    return spec.format("{name}@{version}/{hash:7}")


def _format_spec_with_prefix(spec):
    return f"{_format_spec(spec)} [{spec.prefix}]"


def _parse_numeric_selection(raw, max_index, allow_multiple):
    text = raw.strip().lower()

    if not text and allow_multiple:
        return []

    if allow_multiple and text == "all":
        return list(range(1, max_index + 1))

    values = []
    chunks = [chunk.strip() for chunk in text.split(",") if chunk.strip()]
    if not chunks:
        raise ValueError("No selection provided")

    for chunk in chunks:
        if "-" in chunk:
            parts = [x.strip() for x in chunk.split("-", 1)]
            if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
                raise ValueError(f"Invalid range: {chunk}")
            start = int(parts[0])
            end = int(parts[1])
            if start > end:
                raise ValueError(f"Invalid range: {chunk}")
            values.extend(range(start, end + 1))
        else:
            if not chunk.isdigit():
                raise ValueError(f"Invalid selection value: {chunk}")
            values.append(int(chunk))

    if not allow_multiple and len(values) != 1:
        raise ValueError("Choose exactly one item")

    for idx in values:
        if idx < 1 or idx > max_index:
            raise ValueError(f"Selection {idx} is out of range")

    deduped = []
    seen = set()
    for idx in values:
        if idx not in seen:
            deduped.append(idx)
            seen.add(idx)
    return deduped


def _prompt_single_choice(prompt, options, formatter):
    tty.msg(prompt)
    for i, option in enumerate(options, start=1):
        tty.msg(f"  [{i}] {formatter(option)}")

    while True:
        raw = input("Enter a number: ")
        try:
            indices = _parse_numeric_selection(raw, len(options), allow_multiple=False)
            return options[indices[0] - 1]
        except ValueError as err:
            tty.warn(str(err))


def _prompt_multi_choice(prompt, options, formatter):
    tty.msg(prompt)
    for i, option in enumerate(options, start=1):
        tty.msg(f"  [{i}] {formatter(option)}")
    tty.msg("Select one or more entries as comma-separated numbers (or ranges like 2-4).")
    tty.msg("Enter 'all' to select all entries, or press Enter for none.")

    while True:
        raw = input("Selection: ")
        try:
            indices = _parse_numeric_selection(raw, len(options), allow_multiple=True)
            return [options[i - 1] for i in indices]
        except ValueError as err:
            tty.warn(str(err))


def _select_environment_if_needed():
    env = ev.active_environment()
    if env:
        tty.msg(f"Using active environment '{env.name}'.")
        return env

    env_names = sorted(ev.all_environment_names())
    tty.msg("No active environment found.")
    if env_names:
        tty.msg("Select an environment by number, or enter a path to an environment directory:")
        for i, env_name in enumerate(env_names, start=1):
            tty.msg(f"  [{i}] {env_name}")
    else:
        tty.msg("No managed environments found in Spack env list.")
        tty.msg("Enter a path to a Spack environment directory:")

    while True:
        raw = input("Selection: ").strip()
        if not raw:
            tty.warn("No selection provided")
            continue

        if env_names and raw.isdigit():
            idx = int(raw)
            if idx < 1 or idx > len(env_names):
                tty.warn(f"Selection {idx} is out of range")
                continue
            env = ev.read(env_names[idx - 1])
            break

        env_arg = os.path.abspath(os.path.expanduser(raw))
        try:
            env = ev.environment_from_name_or_dir(env_arg)
            break
        except Exception as err:
            tty.warn(f"Invalid environment selection: {err}")

    ev.activate(env)
    tty.msg(f"Activated environment '{env.name}'.")
    return env


def _select_python_installation(env):
    python_specs = [spec for spec in env.all_specs() if spec.installed and spec.name == "python"]
    if not python_specs:
        raise SpackError(
            "No installed Python specs found in this environment. Install one before creating a venv."
        )

    return _prompt_single_choice(
        "Select Python installation for the virtual environment:",
        python_specs,
        formatter=_format_spec_with_prefix,
    )


def _is_python_package_spec(spec):
    try:
        pkg = spec.package
    except Exception:
        return False

    try:
        from spack_repo.builtin.build_systems.python import PythonPackage

        return isinstance(pkg, PythonPackage)
    except Exception:
        return any(cls.__name__ == "PythonPackage" for cls in pkg.__class__.mro())


def _select_python_packages(env):
    python_package_specs = [
        spec for spec in env.all_specs() if spec.installed and _is_python_package_spec(spec)
    ]

    if not python_package_specs:
        tty.warn("No installed PythonPackage specs found; creating venv without extra package paths.")
        return []

    selected = _prompt_multi_choice(
        "Select PythonPackage specs to expose in the virtual environment:",
        python_package_specs,
        formatter=_format_spec_with_prefix,
    )

    duplicate_names = [name for name, count in Counter(spec.name for spec in selected).items() if count > 1]
    if duplicate_names:
        raise SpackError(
            "Invalid selection: multiple specs were selected for the same package name: "
            + ", ".join(sorted(duplicate_names))
        )

    return selected


def _gather_python_paths(specs):
    collected = []
    for spec in specs:
        try:
            python_dep = spec["python"]
            python_pkg = python_dep.package
            relpaths = {python_pkg.purelib, python_pkg.platlib}
        except Exception:
            relpaths = set()

        for relpath in relpaths:
            candidate = os.path.join(str(spec.prefix), relpath)
            if os.path.isdir(candidate):
                collected.append(candidate)

    unique = []
    seen = set()
    for path in collected:
        if path not in seen:
            unique.append(path)
            seen.add(path)
    return unique


def _detect_venv_site_packages(venv_python):
    cmd = [
        venv_python,
        "-c",
        "import site; print('\\n'.join(site.getsitepackages()))",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    candidates = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for path in candidates:
        if os.path.isdir(path):
            return path
    raise SpackError("Could not locate site-packages directory in the created virtual environment.")


def _write_integration_pth(venv_path, python_paths):
    if not python_paths:
        return None

    venv_python = os.path.join(venv_path, "bin", "python")
    site_packages_dir = _detect_venv_site_packages(venv_python)
    pth_file = os.path.join(site_packages_dir, "spack_selected_packages.pth")

    with open(pth_file, "w", encoding="utf-8") as handle:
        handle.write("\n".join(python_paths))
        handle.write("\n")

    return pth_file


def _create_venv(python_spec, venv_path, python_paths):
    python_exe = os.path.join(str(python_spec.prefix), "bin", "python")
    if not os.path.isfile(python_exe):
        raise SpackError(f"Selected Python executable not found: {python_exe}")

    if os.path.exists(venv_path):
        raise SpackError(f"Target venv path already exists: {venv_path}")

    parent_dir = os.path.dirname(os.path.abspath(venv_path))
    os.makedirs(parent_dir, exist_ok=True)

    cmd_env = os.environ.copy()
    if python_paths:
        existing_pythonpath = cmd_env.get("PYTHONPATH")
        cmd_env["PYTHONPATH"] = os.pathsep.join(
            python_paths + ([existing_pythonpath] if existing_pythonpath else [])
        )

    subprocess.run([python_exe, "-m", "venv", venv_path], env=cmd_env, check=True)


def create_python_venv(parser, args):
    """Handle create-python-venv command."""
    try:
        env = _select_environment_if_needed()

        python_spec = _select_python_installation(env)
        python_packages = _select_python_packages(env)

        python_paths = _gather_python_paths(python_packages)

        _create_venv(python_spec, args.venv_path, python_paths)
        pth_file = _write_integration_pth(args.venv_path, python_paths)

        tty.msg(f"Created virtual environment at '{args.venv_path}'.")
        tty.msg(f"Python interpreter: {_format_spec(python_spec)}")

        if python_packages:
            tty.msg(f"Selected {len(python_packages)} PythonPackage spec(s).")
            if pth_file:
                tty.msg(f"Integrated package paths via {pth_file}")
            else:
                tty.warn(
                    "Selected packages did not expose matching Python package directories "
                    "(purelib/platlib) in their prefixes."
                )
        else:
            tty.msg("No PythonPackage specs selected.")

        tty.msg(f"Activate with: source {args.venv_path}/bin/activate")
        return 0
    except subprocess.CalledProcessError as err:
        raise SpackError(f"Failed to create virtual environment: {err}")
