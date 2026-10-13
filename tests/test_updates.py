import subprocess

from wasp import updates as U


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def make_repos(tmp_path, version="2.1.0"):
    src = tmp_path / "src"
    (src / "wasp").mkdir(parents=True)
    (src / "wasp" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    git(src, "init", "-q", "-b", "main")
    git(src, "add", "-A")
    git(src, "commit", "-qm", "v1")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(remote)], check=True)
    pi = tmp_path / "pi"
    subprocess.run(["git", "clone", "-q", str(remote), str(pi)], check=True)
    return src, remote, pi


def test_up_to_date(tmp_path):
    _, _, pi = make_repos(tmp_path)
    r = U.check(str(pi))
    assert r["status"] == U.CURRENT and r["behind"] == 0 and r["remote_version"] == "2.1.0"


def test_newer_version_available(tmp_path):
    src, remote, pi = make_repos(tmp_path)
    (src / "wasp" / "__init__.py").write_text('__version__ = "2.2.0"\n')
    git(src, "commit", "-qam", "v2")
    git(src, "push", "-q", str(remote), "main")
    r = U.check(str(pi))
    assert r["status"] == U.AVAILABLE and r["behind"] == 1 and r["remote_version"] == "2.2.0"
    # Checking never changes the installed code.
    assert '"2.1.0"' in (pi / "wasp" / "__init__.py").read_text()


def test_unreachable_remote_is_offline(tmp_path):
    _, remote, pi = make_repos(tmp_path)
    git(pi, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    assert U.check(str(pi))["status"] == U.OFFLINE


def test_not_a_git_checkout(tmp_path):
    assert U.check(str(tmp_path))["status"] == U.UNAVAILABLE
