"""SDK dylib colocation helper — pure filesystem logic, no real pyrfc/SAP needed."""

from __future__ import annotations

from pathlib import Path

from sapgui_mcp.backends import _sdk


def test_candidate_libdirs_includes_sapnwrfc_home(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SAPNWRFC_HOME", "/opt/sdk")
    dirs = _sdk._candidate_sdk_libdirs()
    assert Path("/opt/sdk/lib") in dirs


def test_candidate_libdirs_honours_explicit_lib_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("SAPGUI_MCP_SDK_LIB", "/custom/lib")
    assert _sdk._candidate_sdk_libdirs()[0] == Path("/custom/lib")


def test_candidate_libdirs_never_crawls_filesystem(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Regression guard: this list must stay a small, bounded set of explicit paths.
    monkeypatch.delenv("SAPGUI_MCP_SDK_LIB", raising=False)
    monkeypatch.delenv("SAPNWRFC_HOME", raising=False)
    assert len(_sdk._candidate_sdk_libdirs()) <= 8


def test_find_sdk_libdir_returns_dir_containing_lib(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    good = tmp_path / "good"
    good.mkdir()
    (good / "libsapnwrfc.dylib").write_text("lib")
    monkeypatch.setattr(_sdk, "_candidate_sdk_libdirs", lambda: [tmp_path / "missing", good])
    assert _sdk._find_sdk_libdir() == good


def test_find_sdk_libdir_none_when_nothing_found(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(_sdk, "_candidate_sdk_libdirs", lambda: [tmp_path / "nope"])
    assert _sdk._find_sdk_libdir() is None


def test_pyrfc_dir_resolves_installed_package() -> None:
    d = _sdk._pyrfc_dir()
    assert d is None or d.name == "pyrfc"


def test_copy_failure_is_quiet(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pkg, src = tmp_path / "pyrfc", tmp_path / "sdklib"
    pkg.mkdir()
    src.mkdir()
    for lib in _sdk._REQUIRED:
        (src / lib).write_text("real-lib")
    monkeypatch.setattr(_sdk, "_pyrfc_dir", lambda: pkg)
    monkeypatch.setattr(_sdk, "_find_sdk_libdir", lambda: src)
    monkeypatch.setattr(_sdk.shutil, "copy2", _raise_oserror)
    _sdk.ensure_sdk_dylibs()  # read-only site-packages must not crash the server
    assert not any((pkg / lib).exists() for lib in _sdk._REQUIRED)


def _raise_oserror(*args: object, **kwargs: object) -> None:
    raise OSError("read-only file system")


def test_ensure_noop_when_all_present(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pkg = tmp_path / "pyrfc"
    pkg.mkdir()
    for lib in _sdk._REQUIRED:
        (pkg / lib).write_text("stub")
    monkeypatch.setattr(_sdk, "_pyrfc_dir", lambda: pkg)
    called = {"find": False}
    monkeypatch.setattr(_sdk, "_find_sdk_libdir", lambda: called.__setitem__("find", True))
    _sdk.ensure_sdk_dylibs()
    assert called["find"] is False  # short-circuited: no SDK search needed


def test_ensure_copies_missing_libs(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pkg = tmp_path / "pyrfc"
    src = tmp_path / "sdklib"
    pkg.mkdir()
    src.mkdir()
    for lib in _sdk._REQUIRED:
        (src / lib).write_text("real-lib")
    monkeypatch.setattr(_sdk, "_pyrfc_dir", lambda: pkg)
    monkeypatch.setattr(_sdk, "_find_sdk_libdir", lambda: src)
    _sdk.ensure_sdk_dylibs()
    assert all((pkg / lib).exists() for lib in _sdk._REQUIRED)


def test_ensure_gives_up_quietly_when_no_sdk(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    pkg = tmp_path / "pyrfc"
    pkg.mkdir()  # empty -> libs missing
    monkeypatch.setattr(_sdk, "_pyrfc_dir", lambda: pkg)
    monkeypatch.setattr(_sdk, "_find_sdk_libdir", lambda: None)
    _sdk.ensure_sdk_dylibs()  # must not raise
    assert not any((pkg / lib).exists() for lib in _sdk._REQUIRED)
