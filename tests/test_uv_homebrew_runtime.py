"""Native uv path-pin contract, using disposable projects and existing interpreters.

Set DIDA_TEST_UV_PYTHON and DIDA_TEST_UV_ALTERNATE_PYTHON to two different
installed Python versions to exercise rebuilding without downloading Python.
The stable entry is a temporary symlink, never a real Homebrew installation.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


IDENTITY = """
import json, sys
from pathlib import Path
print(json.dumps({
    'version': list(sys.version_info[:3]),
    'base_prefix': str(Path(sys.base_prefix).resolve()),
}))
"""
SMOKE = """
import dida_v2_client, keyring, tzdata
from keyring.backends.null import Keyring
assert isinstance(keyring.get_keyring(), Keyring)
""" + IDENTITY


@pytest.fixture
def uv_project(tmp_path):
    uv = shutil.which("uv")
    primary = os.environ.get("DIDA_TEST_UV_PYTHON")
    alternate = os.environ.get("DIDA_TEST_UV_ALTERNATE_PYTHON")
    if not uv or not primary or not alternate:
        pytest.skip("native uv tests need uv and two explicit installed interpreters")
    assert uv is not None and primary is not None and alternate is not None
    source = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "uv.lock", "README.md"):
        shutil.copy2(source / name, project / name)
    shutil.copytree(source / "src", project / "src", ignore=shutil.ignore_patterns("__pycache__"))
    home = tmp_path / "home"
    home.mkdir()
    guard = tmp_path / "guard"
    guard.mkdir()
    # Child Python processes must not contact accounts, even if smoke code changes.
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "def deny(*args, **kwargs):\n"
        "    raise AssertionError('offline runtime test: networking forbidden')\n"
        "socket.socket.connect = deny\n"
        "socket.socket.connect_ex = deny\n"
        "socket.create_connection = deny\n"
        "socket.getaddrinfo = deny\n",
        encoding="utf-8",
    )
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "TMPDIR": str(tmp_path),
        "UV_PYTHON_INSTALL_DIR": str(home / "managed-python"),
        "PYTHONPATH": str(guard),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    # Reuse package cache, not user credentials or interpreter-selection overrides.
    if os.environ.get("UV_CACHE_DIR"):
        env["UV_CACHE_DIR"] = os.environ["UV_CACHE_DIR"]
    project.joinpath("uv.toml").write_text(
        'python-preference = "only-system"\npython-downloads = "never"\n',
        encoding="utf-8",
    )

    def command(*args, expected=0):
        result = subprocess.run(
            [uv, *args], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == expected, result.stdout + result.stderr
        return result

    def identity(python):
        result = subprocess.run(
            [python, "-c", IDENTITY], cwd=tmp_path, env=env,
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    primary_id, alternate_id = identity(primary), identity(alternate)
    assert primary_id["version"] != alternate_id["version"], "use different interpreter versions"
    try:
        yield project, command, primary, alternate, primary_id, alternate_id
    finally:
        shutil.rmtree(project / ".venv", ignore_errors=True)
        assert not (home / "managed-python").exists(), "uv must not install a managed Python"


def pin(project, command, python):
    command(
        "python", "pin", "--project", str(project), "--no-managed-python",
        "--no-python-downloads", str(python),
    )
    assert (project / ".python-version").read_text().strip() == str(python)


def run(project, command, *args, expected=0):
    # Deliberately no --python: local pin/config must control native uv selection.
    return command(
        "run", "--project", str(project), "--locked", "--extra", "secure-store",
        "--no-python-downloads", *args, expected=expected,
    )


def assert_runtime(result, identity):
    assert json.loads(result.stdout) == identity


@pytest.mark.parametrize("entry_kind", ["file", "symlink"])
def test_gitignore_ignores_venv_file_or_symlink(tmp_path, request, entry_kind):
    if entry_kind == "symlink":
        # Share the native tests' explicit prerequisites, not ordinary Windows runs.
        request.getfixturevalue("uv_project")
    git = shutil.which("git")
    if not git:
        pytest.skip("Git-ignore regression needs git")
    assert git is not None
    source = Path(__file__).resolve().parents[1]
    repo = tmp_path / "git-project"
    repo.mkdir()
    shutil.copy2(source / ".gitignore", repo / ".gitignore")
    home = tmp_path / "git-home"
    home.mkdir()
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(home),
        "USERPROFILE": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(
        [git, "init", "--quiet"], cwd=repo, env=env,
        capture_output=True, text=True, timeout=30, check=True,
    )
    entry = repo / ".venv"
    if entry_kind == "symlink":
        target = tmp_path / "git-external-venv"
        target.mkdir()
        entry.symlink_to(target, target_is_directory=True)
    else:
        entry.write_text("external venv placeholder\n", encoding="utf-8")
    result = subprocess.run(
        [git, "status", "--short", "--untracked-files=all", "--", ".venv"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=30, check=True,
    )
    assert not result.stdout, result.stdout


def test_first_sync_and_external_project_cli_keep_secure_store(uv_project):
    project, command, primary, _, primary_id, _ = uv_project
    pin(project, command, primary)
    assert not (project / ".venv").exists()
    command(
        "sync", "--project", str(project), "--locked", "--extra", "secure-store",
        "--no-python-downloads",
    )
    assert_runtime(run(project, command, "python", "-c", SMOKE), primary_id)
    help_result = run(project, command, "dida-v2", "--profile", "ticktick", "--help")
    assert "usage: dida-v2" in help_result.stdout
    assert "--profile" in help_result.stdout
    assert "--no-headless" in help_result.stdout


def test_existing_other_python_venv_is_rebuilt_from_pin(uv_project):
    project, command, primary, alternate, primary_id, alternate_id = uv_project
    command("venv", "--python", alternate, "--no-python-downloads", str(project / ".venv"))
    before = command(
        "run", "--project", str(project), "--no-sync", "--no-python-downloads",
        "python", "-c", IDENTITY,
    )
    assert_runtime(before, alternate_id)
    pin(project, command, primary)
    assert_runtime(run(project, command, "python", "-c", SMOKE), primary_id)


def test_stable_entry_retarget_rebuilds_and_retains_secure_store(uv_project, tmp_path):
    project, command, primary, alternate, primary_id, alternate_id = uv_project
    entry = tmp_path / "python3"
    entry.symlink_to(primary)
    pin(project, command, entry)
    assert_runtime(run(project, command, "python", "-c", SMOKE), primary_id)
    entry.unlink()  # Only our temporary entry; both real interpreters remain intact.
    entry.symlink_to(alternate)
    assert_runtime(run(project, command, "python", "-c", SMOKE), alternate_id)
    assert (project / ".python-version").read_text().strip() == str(entry)


def test_external_venv_symlink_survives_stable_entry_rebuilds(uv_project, tmp_path):
    project, command, primary, alternate, primary_id, alternate_id = uv_project
    external = tmp_path / "external-venv"
    link = project / ".venv"
    entry = tmp_path / "python3"
    try:
        command("venv", "--python", primary, "--no-python-downloads", str(external))
        link.symlink_to(external, target_is_directory=True)
        entry.symlink_to(primary)
        pin(project, command, entry)
        for index, (python, identity) in enumerate((
            (primary, primary_id), (alternate, alternate_id), (primary, primary_id),
        )):
            if index:
                entry.unlink()  # Retarget only our temporary stable entry.
                entry.symlink_to(python)
            assert_runtime(run(project, command, "python", "-c", SMOKE), identity)
            help_result = run(project, command, "dida-v2", "--help")
            assert "usage: dida-v2" in help_result.stdout
            assert "--profile" in help_result.stdout
            assert "--no-headless" in help_result.stdout
            assert link.is_symlink()
            assert link.resolve(strict=True) == external.resolve(strict=True)
            assert (project / ".python-version").read_text().strip() == str(entry)
    finally:
        if link.is_symlink():
            link.unlink()
        if entry.is_symlink():
            entry.unlink()
        if external.exists():
            shutil.rmtree(external)


@pytest.mark.parametrize("existing_venv", [False, True])
def test_missing_pinned_entry_fails_without_fallback(uv_project, tmp_path, existing_venv):
    project, command, primary, _, primary_id, _ = uv_project
    entry = tmp_path / "python3"
    entry.symlink_to(primary)
    pin(project, command, entry)
    if existing_venv:
        assert_runtime(run(project, command, "python", "-c", SMOKE), primary_id)
    entry.unlink()
    result = run(project, command, "python", "-c", SMOKE, expected=2)
    assert "No interpreter found at path" in result.stderr
    assert entry.name in result.stderr
    assert not result.stdout


def test_wrong_pin_is_detected_by_runtime_assertion(uv_project):
    project, command, _, alternate, primary_id, alternate_id = uv_project
    pin(project, command, alternate)
    result = run(project, command, "python", "-c", SMOKE)
    with pytest.raises(AssertionError):
        assert_runtime(result, primary_id)
    assert_runtime(result, alternate_id)
