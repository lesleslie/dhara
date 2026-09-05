"""Tests for dhara.tools.mermaid_validator.renderer.

Targets ≥90% line coverage. The renderer glues a Node.js subprocess to a
fenced-block extractor; the surface is small but every code path has
subtle env-var and allow-list branches. We exercise each branch with
monkeypatched filesystem/env/subprocess state so the suite runs
without a real mermaid-cli or jsdom install.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dhara.tools.mermaid_validator.renderer import (
    DEFAULT_JSDOM_LOCATIONS,
    DEFAULT_MERMAID_PREFIXES,
    DEFAULT_SKIP_DIRS,
    MERMAID_FENCE_RE,
    MermaidBlock,
    MermaidValidationError,
    _is_trusted_mermaid_path,
    _locate_jsdom,
    _locate_mermaid_core,
    _parse_validator_results,
    _resolve_validator_runtime,
    _run_validator_subprocess,
    extract_mermaid_blocks,
    find_broken_mermaid_blocks,
    iter_markdown_files,
    print_errors,
    validate_mermaid_blocks,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_mermaid_block_dataclass_attributes() -> None:
    """MermaidBlock holds file/line/code and is hashable (frozen)."""
    block = MermaidBlock(file=Path("/tmp/x.md"), line=3, code="graph TD; A-->B;")
    assert block.file == Path("/tmp/x.md")
    assert block.line == 3
    assert block.code == "graph TD; A-->B;"
    # Frozen → hashable.
    assert hash(block) == hash(block)


@pytest.mark.unit
def test_relpath_under_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """relpath returns path relative to cwd when the file is under cwd."""
    monkeypatch.chdir(tmp_path)
    nested = tmp_path / "docs" / "x.md"
    err = MermaidValidationError(file=nested, line=1, error="boom")
    assert err.relpath == "docs/x.md"


@pytest.mark.unit
def test_relpath_outside_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """relpath falls back to str(file) when the file is not under cwd."""
    monkeypatch.chdir(tmp_path)
    elsewhere = Path("/tmp/outside-tree/file.md")
    err = MermaidValidationError(file=elsewhere, line=7, error="boom")
    assert err.relpath == str(elsewhere)


# ---------------------------------------------------------------------------
# iter_markdown_files / extract_mermaid_blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_iter_markdown_files_skips_default_dirs(tmp_path: Path) -> None:
    """iter_markdown_files descends the tree but skips DEFAULT_SKIP_DIRS members."""
    (tmp_path / "keep.md").write_text("ok")
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "hidden.md").write_text("skip")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.md").write_text("skip")
    nested = tmp_path / "docs"
    nested.mkdir()
    (nested / "guide.md").write_text("ok")

    found = iter_markdown_files(tmp_path)
    names = sorted(p.name for p in found)
    assert names == ["guide.md", "keep.md"]


@pytest.mark.unit
def test_iter_markdown_files_custom_skip(tmp_path: Path) -> None:
    """A caller-provided skip_dirs tuple overrides DEFAULT_SKIP_DIRS."""
    (tmp_path / "keep.md").write_text("ok")
    (tmp_path / "skipme").mkdir()
    (tmp_path / "skipme" / "x.md").write_text("ignored")

    found = iter_markdown_files(tmp_path, skip_dirs=("skipme",))
    assert [p.name for p in found] == ["keep.md"]


@pytest.mark.unit
def test_extract_mermaid_blocks_parses_block(tmp_path: Path) -> None:
    """A single fenced mermaid block is returned with the right line number."""
    md = tmp_path / "x.md"
    md.write_text("# title\n\n```mermaid\ngraph TD; A-->B;\n```\n")
    blocks = extract_mermaid_blocks(md)
    assert len(blocks) == 1
    assert blocks[0].file == md
    assert blocks[0].line == 3
    assert "graph TD" in blocks[0].code


@pytest.mark.unit
def test_extract_mermaid_blocks_multiple_and_line_numbers(tmp_path: Path) -> None:
    """Each block reports its own 1-indexed line number."""
    md = tmp_path / "x.md"
    md.write_text(
        "first line\n"
        "second line\n"
        "```mermaid\nflowchart LR; X-->Y;\n```\n"
        "filler\n"
        "more filler\n"
        "```mermaid\nsequenceDiagram; A->>B: hi;\n```\n"
    )
    blocks = extract_mermaid_blocks(md)
    # First block opens after two leading newlines + # header? No — bare text.
    # Count newlines in:
    #   "first line\nsecond line\n```mermaid\n..."
    # So ```mermaid starts after 2 newlines → 1-indexed line = 3.
    # Second ```mermaid starts after several newlines; verify the lines
    # are strictly increasing and both blocks are detected.
    assert len(blocks) == 2
    assert blocks[0].line == 3
    assert blocks[1].line > blocks[0].line


@pytest.mark.unit
def test_extract_mermaid_blocks_returns_empty_for_non_mermaid(tmp_path: Path) -> None:
    """A markdown file with no mermaid fences yields no blocks."""
    md = tmp_path / "x.md"
    md.write_text("just prose, ```python fenced but not mermaid```.")
    assert extract_mermaid_blocks(md) == []


@pytest.mark.unit
def test_extract_mermaid_blocks_returns_empty_for_missing_file(tmp_path: Path) -> None:
    """A missing file is caught and returns [] (not raised)."""
    md = tmp_path / "does-not-exist.md"
    assert extract_mermaid_blocks(md) == []


@pytest.mark.unit
def test_extract_mermaid_blocks_returns_empty_for_undecodable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file that raises UnicodeDecodeError is caught and returns []."""
    md = tmp_path / "bad.md"
    md.write_text("placeholder")

    real_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == md:
            raise UnicodeDecodeError("utf-8", b"\xff\xfe", 0, 1, "bad")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert extract_mermaid_blocks(md) == []


@pytest.mark.unit
def test_extract_mermaid_blocks_handles_oserror(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read_text OSError is also caught and returns []."""
    md = tmp_path / "oserr.md"
    md.write_text("placeholder")

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == md:
            raise OSError("disk gone")
        return "x"

    monkeypatch.setattr(Path, "read_text", fake_read_text)
    assert extract_mermaid_blocks(md) == []


@pytest.mark.unit
def test_mermaid_fence_re_is_compiled() -> None:
    """The regex constant exists and matches a minimal mermaid block."""
    matches = list(MERMAID_FENCE_RE.finditer("```mermaid\ngraph TD\n```\n"))
    assert len(matches) == 1
    assert "graph TD" in matches[0].group(1)


# ---------------------------------------------------------------------------
# _is_trusted_mermaid_path
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_is_trusted_mermaid_path_accepts_allow_listed(tmp_path: Path) -> None:
    """Paths under DEFAULT_MERMAID_PREFIXES are accepted."""
    for prefix in DEFAULT_MERMAID_PREFIXES:
        candidate = Path(prefix) / "fake" / "mermaid.core.mjs"
        assert _is_trusted_mermaid_path(candidate) is True


@pytest.mark.unit
def test_is_trusted_mermaid_path_rejects_unknown(tmp_path: Path) -> None:
    """Paths outside the allow-list are rejected."""
    assert _is_trusted_mermaid_path(Path("/tmp/evil/mermaid.core.mjs")) is False


# ---------------------------------------------------------------------------
# _locate_mermaid_core
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_locate_mermaid_core_env_override_trusted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DHARA_MERMAID_CORE pointing at an allow-listed path returns that path."""
    # Build a path that resolves under one of the DEFAULT_MERMAID_PREFIXES.
    trusted_root = Path(DEFAULT_MERMAID_PREFIXES[0]).resolve()
    fake = trusted_root / "synthetic" / "mermaid.core.mjs"
    monkeypatch.setenv("DHARA_MERMAID_CORE", str(fake))
    try:
        result = _locate_mermaid_core()
    finally:
        monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    assert result == fake


@pytest.mark.unit
def test_locate_mermaid_core_env_override_untrusted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DHARA_MERMAID_CORE outside the allow-list raises RuntimeError."""
    monkeypatch.setenv("DHARA_MERMAID_CORE", "/tmp/attacker/mermaid.core.mjs")
    try:
        with pytest.raises(RuntimeError, match="not under a trusted mermaid-cli prefix"):
            _locate_mermaid_core()
    finally:
        monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)


@pytest.mark.unit
def test_locate_mermaid_core_no_mmdc_on_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If `mmdc` is missing from PATH and no env var, the locator returns None."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _cmd: None)
    assert _locate_mermaid_core() is None


@pytest.mark.unit
def test_locate_mermaid_core_mmdc_untrusted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`mmdc` resolves to a path NOT under a trusted prefix → returns None."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _cmd: "/tmp/not-trusted/bin/mmdc")
    assert _locate_mermaid_core() is None


@pytest.mark.unit
def test_locate_mermaid_core_mmdc_trusted_but_no_node_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the parent walk finds no node_modules, returns None."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    # Place mmdc under the trusted prefix but its parents have no node_modules.
    trusted_prefix = Path(DEFAULT_MERMAID_PREFIXES[0]).resolve()
    fake_bin = trusted_prefix / "11.16.0" / "bin" / "mmdc"
    monkeypatch.setattr("shutil.which", lambda _cmd: str(fake_bin))
    # Ensure is_dir/is_file never accidentally find a real node_modules.
    monkeypatch.setattr(Path, "is_dir", lambda self: False)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert _locate_mermaid_core() is None


@pytest.mark.unit
def test_locate_mermaid_core_node_modules_present_but_no_mermaid_cli(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A parent directory with node_modules but no @mermaid-js/mermaid-cli returns None."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    trusted_prefix = Path(DEFAULT_MERMAID_PREFIXES[0]).resolve()
    fake_bin = trusted_prefix / "11.16.0" / "bin" / "mmdc"
    monkeypatch.setattr("shutil.which", lambda _cmd: str(fake_bin))

    # is_dir returns True for node_modules only when the path endswith node_modules.
    def fake_is_dir(self: Path) -> bool:
        return self.name == "node_modules"

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert _locate_mermaid_core() is None


@pytest.mark.unit
def test_locate_mermaid_core_walks_to_next_candidate_when_core_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If a parent has the mermaid-cli tree but no core file, walker keeps going."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    trusted_prefix = Path(DEFAULT_MERMAID_PREFIXES[0]).resolve()
    fake_bin = trusted_prefix / "bin" / "mmdc"
    monkeypatch.setattr("shutil.which", lambda _cmd: str(fake_bin))

    nm = trusted_prefix / "node_modules"
    cli_dir = nm / "@mermaid-js" / "mermaid-cli"

    def fake_is_dir(self: Path) -> bool:
        # Both `nm` and `cli_dir` exist as directories, so the walker
        # reaches the core-file check. But core.is_file() returns False.
        return self in (nm, cli_dir)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert _locate_mermaid_core() is None


@pytest.mark.unit
def test_locate_mermaid_core_finds_core_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Happy path: returns the located mermaid.core.mjs when all checks pass."""
    monkeypatch.delenv("DHARA_MERMAID_CORE", raising=False)
    trusted_prefix = Path(DEFAULT_MERMAID_PREFIXES[0]).resolve()
    # Place mmdc directly under the trusted prefix so the parent walk
    # reaches the prefix, which is where the (mocked) node_modules lives.
    fake_bin = trusted_prefix / "bin" / "mmdc"
    monkeypatch.setattr("shutil.which", lambda _cmd: str(fake_bin))

    nm = trusted_prefix / "node_modules"
    cli_dir = nm / "@mermaid-js" / "mermaid-cli"
    core_path = (
        cli_dir
        / "node_modules"
        / "mermaid"
        / "dist"
        / "mermaid.core.mjs"
    )

    def fake_is_dir(self: Path) -> bool:
        return self in (nm, cli_dir)

    def fake_is_file(self: Path) -> bool:
        return self == core_path

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(Path, "is_file", fake_is_file)
    assert _locate_mermaid_core() == core_path


# ---------------------------------------------------------------------------
# _locate_jsdom
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_locate_jsdom_env_override_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DHARA_JSDOM pointing at an existing file returns that path."""
    fake = tmp_path / "jsdom" / "lib" / "api.js"
    fake.parent.mkdir(parents=True)
    fake.write_text("// fake")
    monkeypatch.setenv("DHARA_JSDOM", str(fake))
    try:
        assert _locate_jsdom() == fake.resolve()
    finally:
        monkeypatch.delenv("DHARA_JSDOM", raising=False)


@pytest.mark.unit
def test_locate_jsdom_env_override_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DHARA_JSDOM pointing at a non-existent file raises RuntimeError."""
    monkeypatch.setenv("DHARA_JSDOM", "/tmp/no-such-jsdom/api.js")
    try:
        with pytest.raises(RuntimeError, match="does not exist or is not a file"):
            _locate_jsdom()
    finally:
        monkeypatch.delenv("DHARA_JSDOM", raising=False)


@pytest.mark.unit
def test_locate_jsdom_walks_up_to_find_node_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an env override, the walk discovers whatever jsdom exists on disk.

    The dhara repo ships ``node_modules/jsdom/lib/api.js`` (a wave-11 dev
    dep), so the walk always finds *some* api.js. We assert it returns
    the jsdom entry-point — not the env-override path, not an unrelated
    file — and that the discovered file actually exists.
    """
    monkeypatch.delenv("DHARA_JSDOM", raising=False)
    found = _locate_jsdom()
    # The function is fail-closed; on machines without jsdom it returns None.
    if found is None:
        pytest.skip("jsdom not installed in this environment")
    assert found.name == "api.js"
    assert "jsdom" in str(found)
    assert found.is_file()


@pytest.mark.unit
def test_locate_jsdom_returns_none_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no env var and no node_modules/jsdom/lib/api.js on the walk → None."""
    monkeypatch.delenv("DHARA_JSDOM", raising=False)
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    assert _locate_jsdom() is None


# ---------------------------------------------------------------------------
# _resolve_validator_runtime
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_validator_runtime_missing_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If validate_mermaid.mjs is missing, FileNotFoundError is raised."""
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(FileNotFoundError, match="validate_mermaid.mjs not found"):
        _resolve_validator_runtime()


@pytest.mark.unit
def test_resolve_validator_runtime_missing_mermaid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If mermaid-core cannot be located, RuntimeError is raised."""
    def fake_exists(self: Path) -> bool:
        # validate_mermaid.mjs lives next to renderer.py — pretend it exists.
        return self.name == "validate_mermaid.mjs"

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_mermaid_core",
        lambda: None,
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_jsdom",
        lambda: Path("/fake/jsdom.js"),
    )
    with pytest.raises(RuntimeError, match="could not find mermaid/dist/mermaid.core.mjs"):
        _resolve_validator_runtime()


@pytest.mark.unit
def test_resolve_validator_runtime_missing_jsdom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If jsdom cannot be located, RuntimeError is raised."""
    def fake_exists(self: Path) -> bool:
        return self.name == "validate_mermaid.mjs"

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_mermaid_core",
        lambda: Path("/fake/mermaid.core.mjs"),
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_jsdom",
        lambda: None,
    )
    with pytest.raises(RuntimeError, match="could not find jsdom"):
        _resolve_validator_runtime()


@pytest.mark.unit
def test_resolve_validator_runtime_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All three artifacts present → returns the tuple of paths."""
    real_exists = Path.exists

    def fake_exists(self: Path) -> bool:
        if self.name == "validate_mermaid.mjs":
            return True
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", fake_exists)
    runner = Path(__file__).resolve().parent.parent.parent \
        / "dhara" / "tools" / "mermaid_validator" / "validate_mermaid.mjs"
    mermaid_core = Path("/fake/mermaid.core.mjs")
    jsdom = Path("/fake/jsdom.js")
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_mermaid_core",
        lambda: mermaid_core,
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._locate_jsdom",
        lambda: jsdom,
    )
    out = _resolve_validator_runtime()
    assert out == (runner, mermaid_core, jsdom)


# ---------------------------------------------------------------------------
# _run_validator_subprocess
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_run_validator_subprocess_node_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FileNotFoundError from subprocess.run is wrapped in a RuntimeError."""
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        raise FileNotFoundError("node not on PATH")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="node is not on PATH"):
        _run_validator_subprocess("[]", Path("/r.mjs"), Path("/m.mjs"), Path("/j.js"), 1.0)


@pytest.mark.unit
def test_run_validator_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TimeoutExpired is wrapped with payload bytes in the message."""
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        raise subprocess.TimeoutExpired(cmd=["node"], timeout=kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match=r"timed out after .* on .* bytes"):
        _run_validator_subprocess("[]", Path("/r.mjs"), Path("/m.mjs"), Path("/j.js"), 1.0)


@pytest.mark.unit
def test_run_validator_subprocess_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful subprocess.run returns the CompletedProcess as-is."""
    completed = subprocess.CompletedProcess(
        args=["node"], returncode=0, stdout="ok", stderr=""
    )

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess:
        return completed

    monkeypatch.setattr(subprocess, "run", fake_run)
    out = _run_validator_subprocess(
        "[]", Path("/r.mjs"), Path("/m.mjs"), Path("/j.js"), 1.0
    )
    assert out is completed


# ---------------------------------------------------------------------------
# _parse_validator_results
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_validator_results_valid_json() -> None:
    """Valid JSON yields the parsed structure."""
    payload = json.dumps([{"file": "/x.md", "line": 1, "status": "ok"}])
    result = _parse_validator_results(payload)
    assert result == [{"file": "/x.md", "line": 1, "status": "ok"}]


@pytest.mark.unit
def test_parse_validator_results_invalid_json() -> None:
    """Invalid JSON raises RuntimeError with a stdout preview."""
    with pytest.raises(RuntimeError, match="invalid JSON"):
        _parse_validator_results("not json at all")


# ---------------------------------------------------------------------------
# validate_mermaid_blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_validate_mermaid_blocks_empty_returns_empty() -> None:
    """Empty input short-circuits without invoking any subprocess."""
    assert validate_mermaid_blocks([]) == []


@pytest.mark.unit
def test_validate_mermaid_blocks_parses_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Successful subprocess output is converted to MermaidValidationError list."""
    block = MermaidBlock(file=tmp_path / "x.md", line=2, code="graph TD; A-->B;")

    fake_completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps([
            {"file": str(block.file), "line": 2, "status": "error",
             "error": "Syntax error"},
            {"file": str(block.file), "line": 9, "status": "ok"},
        ]),
        stderr="",
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._run_validator_subprocess",
        lambda *a, **k: fake_completed,
    )
    errors = validate_mermaid_blocks([block])
    assert len(errors) == 1
    err = errors[0]
    assert err.file == block.file
    assert err.line == 2
    assert err.error == "Syntax error"


@pytest.mark.unit
def test_validate_mermaid_blocks_nonzero_return(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A non-zero return code raises RuntimeError with stderr excerpt."""
    block = MermaidBlock(file=tmp_path / "x.md", line=1, code="bad")
    fake_completed = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="{}",
        stderr="boom",
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._run_validator_subprocess",
        lambda *a, **k: fake_completed,
    )
    with pytest.raises(RuntimeError, match=r"validate_mermaid.mjs exited 1"):
        validate_mermaid_blocks([block])


@pytest.mark.unit
def test_validate_mermaid_blocks_missing_error_field(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A status='error' entry with no 'error' field surfaces '<unknown error>'."""
    block = MermaidBlock(file=tmp_path / "x.md", line=1, code="bad")
    fake_completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps([{"file": str(block.file), "line": 1, "status": "error"}]),
        stderr="",
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer._run_validator_subprocess",
        lambda *a, **k: fake_completed,
    )
    errors = validate_mermaid_blocks([block])
    assert len(errors) == 1
    assert errors[0].error == "<unknown error>"


# ---------------------------------------------------------------------------
# find_broken_mermaid_blocks
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_broken_mermaid_blocks_with_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """When paths is supplied, it scans exactly those files."""
    md = tmp_path / "x.md"
    md.write_text("```mermaid\ngraph TD\n```\n")

    captured: list[list[MermaidBlock]] = []

    def fake_validate(
        blocks: list[MermaidBlock], timeout: float = 30.0
    ) -> list[MermaidValidationError]:
        captured.append(blocks)
        return []

    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer.validate_mermaid_blocks",
        fake_validate,
    )
    assert find_broken_mermaid_blocks(paths=[md]) == []
    assert len(captured) == 1
    assert captured[0][0].file == md


@pytest.mark.unit
def test_find_broken_mermaid_blocks_default_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """With no root and no paths, defaults to scanning Path.cwd()."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.md").write_text("```mermaid\ngraph TD\n```\n")

    seen_roots: list[Path] = []

    def fake_iter(root: Path) -> list[Path]:
        seen_roots.append(root)
        return [tmp_path / "a.md"]

    def fake_validate(
        blocks: list[MermaidBlock], timeout: float = 30.0
    ) -> list[MermaidValidationError]:
        return []

    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer.iter_markdown_files",
        fake_iter,
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer.validate_mermaid_blocks",
        fake_validate,
    )
    find_broken_mermaid_blocks()
    assert seen_roots == [tmp_path.resolve()]


@pytest.mark.unit
def test_find_broken_mermaid_blocks_with_explicit_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A caller-supplied root is forwarded to iter_markdown_files."""
    seen_roots: list[Path] = []

    def fake_iter(root: Path) -> list[Path]:
        seen_roots.append(root)
        return []

    def fake_validate(
        blocks: list[MermaidBlock], timeout: float = 30.0
    ) -> list[MermaidValidationError]:
        return []

    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer.iter_markdown_files",
        fake_iter,
    )
    monkeypatch.setattr(
        "dhara.tools.mermaid_validator.renderer.validate_mermaid_blocks",
        fake_validate,
    )
    find_broken_mermaid_blocks(root=tmp_path)
    assert seen_roots == [tmp_path.resolve()]


# ---------------------------------------------------------------------------
# print_errors
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_print_errors_empty(capsys: pytest.CaptureFixture[str]) -> None:
    """Empty list prints the success line."""
    print_errors([])
    out = capsys.readouterr().out
    assert "All mermaid blocks parse cleanly" in out


@pytest.mark.unit
def test_print_errors_with_errors(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Non-empty list prints the broken block summary with relpath:line."""
    err = MermaidValidationError(file=tmp_path / "broken.md", line=4, error="oops")
    print_errors([err])
    out = capsys.readouterr().out
    assert "1 broken mermaid block" in out
    assert "broken.md:4" in out
    assert "oops" in out


# ---------------------------------------------------------------------------
# Module constants
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_skip_dirs_constant_shape() -> None:
    """DEFAULT_SKIP_DIRS is a tuple of directory names."""
    assert isinstance(DEFAULT_SKIP_DIRS, tuple)
    assert ".venv" in DEFAULT_SKIP_DIRS
    assert "node_modules" in DEFAULT_SKIP_DIRS


@pytest.mark.unit
def test_mermaid_prefixes_constant_shape() -> None:
    """DEFAULT_MERMAID_PREFIXES is a tuple of absolute path prefixes."""
    assert isinstance(DEFAULT_MERMAID_PREFIXES, tuple)
    for prefix in DEFAULT_MERMAID_PREFIXES:
        assert prefix.startswith("/")


@pytest.mark.unit
def test_jsdom_locations_constant_shape() -> None:
    """DEFAULT_JSDOM_LOCATIONS points at the jsdom entry-point under node_modules."""
    assert isinstance(DEFAULT_JSDOM_LOCATIONS, tuple)
    assert all("jsdom" in p for p in DEFAULT_JSDOM_LOCATIONS)