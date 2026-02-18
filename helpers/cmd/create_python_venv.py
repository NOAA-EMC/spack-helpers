"""Create a Python virtual environment from packages in a Spack environment."""

import os
import shlex
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


def _build_pip_install_args_from_path(raw_path):
    resolved_path = os.path.abspath(os.path.expanduser(raw_path))

    if os.path.isdir(resolved_path):
        pyproject_path = os.path.join(resolved_path, "pyproject.toml")
        if os.path.isfile(pyproject_path):
            return [resolved_path], f"pyproject.toml in {resolved_path}"
        raise ValueError("Directory does not contain pyproject.toml")

    if not os.path.isfile(resolved_path):
        raise ValueError(f"Path does not exist: {resolved_path}")

    basename = os.path.basename(resolved_path)
    if basename == "requirements.txt":
        return ["-r", resolved_path], f"requirements.txt at {resolved_path}"
    if basename == "pyproject.toml":
        return [os.path.dirname(resolved_path)], f"pyproject.toml at {resolved_path}"

    raise ValueError(
        "Path must be requirements.txt, pyproject.toml, or a directory containing pyproject.toml"
    )


def _select_pip_install_args():
    tty.msg("Choose how to populate the new virtual environment with pip install:")
    tty.msg("  [1] Use requirements.txt in current directory")
    tty.msg("  [2] Use pyproject.toml in current directory")
    tty.msg("  [3] Specify path to requirements.txt/pyproject.toml")
    tty.msg("  [4] Enter a manual list of pip packages")
    tty.msg("Press Enter to skip pip installation.")

    while True:
        selection = input("Selection: ").strip()
        if not selection:
            return None, None

        if selection == "1":
            req_path = os.path.abspath("requirements.txt")
            if not os.path.isfile(req_path):
                tty.warn(f"requirements.txt not found in current directory: {req_path}")
                continue
            return ["-r", req_path], f"requirements.txt at {req_path}"

        if selection == "2":
            pyproject_path = os.path.abspath("pyproject.toml")
            if not os.path.isfile(pyproject_path):
                tty.warn(f"pyproject.toml not found in current directory: {pyproject_path}")
                continue
            return [os.getcwd()], f"pyproject.toml in {os.getcwd()}"

        if selection == "3":
            raw_path = input(
                "Enter path to requirements.txt, pyproject.toml, or directory with pyproject.toml: "
            ).strip()
            if not raw_path:
                tty.warn("No path provided")
                continue
            try:
                return _build_pip_install_args_from_path(raw_path)
            except ValueError as err:
                tty.warn(str(err))
                continue

        if selection == "4":
            raw_packages = input("Enter pip packages (space-separated): ").strip()
            try:
                packages = shlex.split(raw_packages)
            except ValueError as err:
                tty.warn(f"Invalid package list: {err}")
                continue

            if not packages:
                tty.warn("No packages provided")
                continue

            return packages, "manual package list"

        tty.warn("Invalid selection. Choose 1, 2, 3, 4, or press Enter to skip.")


def _install_pip_packages(venv_path, pip_install_args):
    if not pip_install_args:
        return False

    venv_pip = os.path.join(venv_path, "bin", "pip")
    if not os.path.isfile(venv_pip):
        raise SpackError(f"pip executable not found in created virtual environment: {venv_pip}")

    try:
        subprocess.run([venv_pip, "install"] + pip_install_args, check=True)
    except subprocess.CalledProcessError as err:
        raise SpackError(f"Failed to install pip packages in virtual environment: {err}")

    return True


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
        pip_install_args, pip_install_source = _select_pip_install_args()

        python_paths = _gather_python_paths(python_packages)

        _create_venv(python_spec, args.venv_path, python_paths)
        pth_file = _write_integration_pth(args.venv_path, python_paths)
        pip_installed = _install_pip_packages(args.venv_path, pip_install_args)

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

        if pip_installed:
            tty.msg(f"Installed pip packages using {pip_install_source}.")
        else:
            tty.msg("Skipped pip package installation.")

        tty.msg(f"Activate with: source {args.venv_path}/bin/activate")
        return 0
    except subprocess.CalledProcessError as err:
        raise SpackError(f"Failed to create virtual environment: {err}")
