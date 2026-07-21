"""Unit tests for fetch-deps command spec selection logic."""

import types

import pytest

import spack.extensions

spack.extensions.load_extension("helpers")
from spack.extensions.helpers.cmd import fetch_deps as cmd


class _FakeSpec:
    """Minimal stand-in for a Spack spec used by the fetch-deps selection logic."""

    def __init__(self, name, concrete=True, deps=()):
        self.name = name
        self.concrete = concrete
        self._deps = set(deps)

    def satisfies(self, abstract_spec):
        return self.name == abstract_spec

    def dag_hash(self):
        return f"{self.name}-hash"

    def __contains__(self, dep_name):
        return dep_name in self._deps

    def __repr__(self):
        return f"<FakeSpec {self.name!r}>"


class _FakeEnv:
    def __init__(self, all_specs, roots=None):
        self._all_specs = all_specs
        # concretized_specs() returns (abstract, concrete) pairs for roots only
        self._roots = roots if roots is not None else all_specs

    def all_specs(self):
        return list(self._all_specs)

    def concretized_specs(self):
        return [(s, s) for s in self._roots]


def _make_args(**kwargs):
    defaults = dict(deps_command="go", specs=[], use_spack_go=False, use_spack_rust=False)
    defaults.update(kwargs)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Regression test: the core bug fixed by switching to all_specs()
# ---------------------------------------------------------------------------

def test_dep_with_go_not_a_root_is_included(monkeypatch):
    """A concretized dependency that has 'go' must be selected even if it is
    not a root spec (and therefore absent from concretized_specs()).

    Before the fix, only roots were examined and this spec would be silently
    skipped.  After the fix, all_specs() includes it.
    """
    root_no_go = _FakeSpec("my-meta-app", concrete=True, deps=[])
    go_dep = _FakeSpec("go-client", concrete=True, deps=["go"])

    env = _FakeEnv(
        all_specs=[root_no_go, go_dep],
        roots=[root_no_go],   # go-client is a dependency, not a root
    )

    monkeypatch.setattr(cmd, "active_environment", lambda: env)

    called_with = {}
    monkeypatch.setattr(
        cmd, "fetch_go_dependencies",
        lambda specs, use_spack_go=False: called_with.update({"specs": list(specs)})
    )
    monkeypatch.setattr(cmd.tty, "warn", lambda _msg: None)

    result = cmd.fetch_deps(parser=None, args=_make_args())

    assert result == 0
    assert called_with["specs"] == [go_dep], (
        "go-client should be selected even though it is a dependency, not a root"
    )


def test_user_specified_dep_spec_is_matched(monkeypatch):
    """When the user provides an explicit spec name that is a dependency (not a
    root), it should be found and selected.

    Before the fix, the user would receive a 'No concretized specs' warning
    even though the spec was fully concretized.
    """
    root = _FakeSpec("my-app", concrete=True, deps=["go"])
    go_dep = _FakeSpec("go-client", concrete=True, deps=["go"])

    env = _FakeEnv(
        all_specs=[root, go_dep],
        roots=[root],   # go-client is a dependency, not a root
    )

    monkeypatch.setattr(cmd, "active_environment", lambda: env)

    called_with = {}
    monkeypatch.setattr(
        cmd, "fetch_go_dependencies",
        lambda specs, use_spack_go=False: called_with.update({"specs": list(specs)})
    )

    warns = []
    monkeypatch.setattr(cmd.tty, "warn", lambda msg: warns.append(msg))

    result = cmd.fetch_deps(parser=None, args=_make_args(specs=["go-client"]))

    assert result == 0
    assert called_with["specs"] == [go_dep]
    assert not any("go-client" in w for w in warns), (
        "should not warn about go-client being unfound when it is a concretized dependency"
    )


# ---------------------------------------------------------------------------
# Additional correctness checks
# ---------------------------------------------------------------------------

def test_non_concrete_specs_are_excluded(monkeypatch):
    """Specs that are not concrete must never be passed to the fetch function."""
    concrete = _FakeSpec("concrete-client", concrete=True, deps=["go"])
    abstract = _FakeSpec("abstract-client", concrete=False, deps=["go"])

    env = _FakeEnv(all_specs=[concrete, abstract])

    monkeypatch.setattr(cmd, "active_environment", lambda: env)

    called_with = {}
    monkeypatch.setattr(
        cmd, "fetch_go_dependencies",
        lambda specs, use_spack_go=False: called_with.update({"specs": list(specs)})
    )
    monkeypatch.setattr(cmd.tty, "warn", lambda _msg: None)

    cmd.fetch_deps(parser=None, args=_make_args())

    assert called_with["specs"] == [concrete]


def test_warns_for_truly_missing_spec(monkeypatch):
    """A user-supplied spec name that does not match any concrete spec should
    produce a warning."""
    root = _FakeSpec("my-app", concrete=True, deps=["go"])

    env = _FakeEnv(all_specs=[root])

    monkeypatch.setattr(cmd, "active_environment", lambda: env)
    monkeypatch.setattr(cmd, "fetch_go_dependencies", lambda specs, **_kw: None)

    warns = []
    monkeypatch.setattr(cmd.tty, "warn", lambda msg: warns.append(msg))

    cmd.fetch_deps(parser=None, args=_make_args(specs=["nonexistent"]))

    assert any("nonexistent" in w for w in warns)
