"""Fail fast when a test attempts to modify real PaperFlow runtime state."""

from __future__ import annotations

import builtins
import shutil
import sqlite3
from pathlib import Path

import pytest

from paperflow.config import PROJECT_ROOT


@pytest.fixture(autouse=True)
def block_real_runtime_writes(monkeypatch: pytest.MonkeyPatch):
    protected_file = (PROJECT_ROOT / "config.yaml").resolve()
    protected_dirs = tuple(
        path.resolve() for path in (PROJECT_ROOT / "workspace", PROJECT_ROOT / "paper_repo")
    )

    def is_protected(path: object) -> bool:
        if not isinstance(path, (str, Path)):
            return False
        candidate = Path(path).resolve()
        return candidate == protected_file or any(
            candidate == directory or directory in candidate.parents
            for directory in protected_dirs
        )

    def reject(path: object, operation: str) -> None:
        if is_protected(path):
            raise AssertionError(f"Test attempted real runtime write via {operation}: {path}")

    original_mkdir = Path.mkdir
    original_write_text = Path.write_text
    original_write_bytes = Path.write_bytes
    original_unlink = Path.unlink
    original_touch = Path.touch
    original_path_open = Path.open
    original_open = builtins.open

    def guarded_mkdir(self: Path, *args, **kwargs):
        reject(self, "Path.mkdir")
        return original_mkdir(self, *args, **kwargs)

    def guarded_write_text(self: Path, *args, **kwargs):
        reject(self, "Path.write_text")
        return original_write_text(self, *args, **kwargs)

    def guarded_write_bytes(self: Path, *args, **kwargs):
        reject(self, "Path.write_bytes")
        return original_write_bytes(self, *args, **kwargs)

    def guarded_unlink(self: Path, *args, **kwargs):
        reject(self, "Path.unlink")
        return original_unlink(self, *args, **kwargs)

    def guarded_touch(self: Path, *args, **kwargs):
        reject(self, "Path.touch")
        return original_touch(self, *args, **kwargs)

    def writes_mode(mode: str) -> bool:
        return any(flag in mode for flag in "wax+")

    def guarded_path_open(self: Path, mode: str = "r", *args, **kwargs):
        if writes_mode(mode):
            reject(self, "Path.open")
        return original_path_open(self, mode, *args, **kwargs)

    def guarded_open(file, mode: str = "r", *args, **kwargs):
        if writes_mode(mode):
            reject(file, "open")
        return original_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    monkeypatch.setattr(Path, "write_text", guarded_write_text)
    monkeypatch.setattr(Path, "write_bytes", guarded_write_bytes)
    monkeypatch.setattr(Path, "unlink", guarded_unlink)
    monkeypatch.setattr(Path, "touch", guarded_touch)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(builtins, "open", guarded_open)

    for name in ("copy", "copy2", "copyfile"):
        original = getattr(shutil, name)

        def guarded_copy(src, dst, *args, _original=original, _name=name, **kwargs):
            reject(dst, f"shutil.{_name}")
            return _original(src, dst, *args, **kwargs)

        monkeypatch.setattr(shutil, name, guarded_copy)

    original_copytree = shutil.copytree
    original_move = shutil.move
    original_rmtree = shutil.rmtree

    def guarded_copytree(src, dst, *args, **kwargs):
        reject(dst, "shutil.copytree")
        return original_copytree(src, dst, *args, **kwargs)

    def guarded_move(src, dst, *args, **kwargs):
        reject(src, "shutil.move source")
        reject(dst, "shutil.move destination")
        return original_move(src, dst, *args, **kwargs)

    def guarded_rmtree(path, *args, **kwargs):
        reject(path, "shutil.rmtree")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "copytree", guarded_copytree)
    monkeypatch.setattr(shutil, "move", guarded_move)
    monkeypatch.setattr(shutil, "rmtree", guarded_rmtree)

    original_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        if database != ":memory:":
            reject(database, "sqlite3.connect")
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
