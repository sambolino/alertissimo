"""Fast-path counterexamples and required-check wiring; no provider imports."""

import os
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.ci_change_scope import classify, yaml_tokens


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def commit(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fixture")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "CI scope fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    for name, content in {
        "README.md": "Before\n",
        "provider.yaml": "values: [1, 2]\nlabel: SN\n",
        "runtime.py": "value = 1\n",
        "setup.py": "version = '1'\n",
        "requirements.txt": "PyYAML\n",
        ".github/workflows/dsl.yml": "name: DSL compiler\n",
    }.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path, commit(tmp_path)


def scope(repo, base, **kwargs):
    return classify(repo, event="pull_request", base=base, **kwargs)


def test_markdown_add_delete_rename_and_yaml_comment_only_are_fast(repo):
    root, base = repo
    (root / "README.md").rename(root / "Renamed guide.md")
    (root / "new.md").write_text("New documentation\n")
    (root / "provider.yaml").write_text("# comment\nvalues: [1, 2] # unchanged\nlabel: SN\n")
    commit(root)
    assert not scope(root, base).run_backend


@pytest.mark.parametrize("text", [
    "values: [1, 3]\nlabel: SN\n",  # scientific value
    "label: SN\nvalues: [1, 2]\n",  # ordered mapping contract
    "values: [1, 2]\nlabel: SN\nlabel: AGN\n",  # duplicate key
    "values: [1, 2]\nlabel: 'SN'\n",  # scalar style is conservative
    "values: [1, 2\n",  # malformed YAML cannot qualify
])
def test_yaml_content_order_duplicates_and_syntax_require_backend(repo, text):
    root, base = repo
    (root / "provider.yaml").write_text(text)
    commit(root)
    assert scope(root, base).run_backend


@pytest.mark.parametrize("old,new", [
    ("x: true\n", "x: 1\n"),
    ("x: 1\n", "x: 1.0\n"),
    ("x: [1, 2]\n", "x: [2, 1]\n"),
    ("x: &a 1\ny: *a\n", "x: &b 1\ny: *b\n"),
    ("x: !one value\n", "x: !two value\n"),
    ("x: |\n  # actual content\n", "x: |\n  # changed content\n"),
])
def test_yaml_tokens_do_not_hide_types_aliases_tags_or_block_content(old, new):
    assert yaml_tokens(old.encode()) != yaml_tokens(new.encode())


@pytest.mark.parametrize("name", ["runtime.py", "setup.py", "requirements.txt", "payload.json"])
def test_any_runtime_dependency_or_other_file_keeps_full_checks(repo, name):
    root, base = repo
    (root / "README.md").write_text("Documentation too\n")
    (root / name).write_text("changed\n")
    commit(root)
    assert scope(root, base).run_backend


@pytest.mark.parametrize("operation", ["add", "delete", "rename", "chmod", "symlink"])
def test_yaml_lifecycle_and_file_types_never_qualify_as_comments(repo, operation):
    root, base = repo
    path = root / "provider.yaml"
    if operation == "add":
        (root / "another.yaml").write_text(path.read_text())
    elif operation == "delete":
        path.unlink()
    elif operation == "rename":
        path.rename(root / "renamed.yaml")
    elif operation == "chmod":
        path.chmod(0o755)
    else:
        path.unlink()
        path.symlink_to("README.md")
    commit(root)
    assert scope(root, base).run_backend


def test_markdown_symlink_is_not_documentation_only(repo):
    root, base = repo
    (root / "link.md").symlink_to("runtime.py")
    commit(root)
    assert scope(root, base).run_backend


def test_ci_infrastructure_has_its_own_fast_checks_but_mixed_runtime_does_not(repo):
    root, base = repo
    (root / ".github/workflows/dsl.yml").write_text("name: changed CI\n")
    commit(root)
    result = scope(root, base)
    assert not result.run_backend and "CI regression tests" in result.reason
    (root / "runtime.py").write_text("value = 2\n")
    commit(root)
    assert scope(root, base).run_backend


def test_deleted_ci_control_file_does_not_receive_a_fast_pass(repo):
    root, base = repo
    (root / ".github/workflows/dsl.yml").unlink()
    commit(root)
    assert scope(root, base).run_backend


def test_complete_pr_diff_includes_earlier_runtime_commits(repo):
    root, base = repo
    (root / "runtime.py").write_text("value = 2\n")
    commit(root)
    (root / "README.md").write_text("Latest commit is documentation\n")
    commit(root)
    assert scope(root, base).run_backend


def test_manual_execution_and_unavailable_base_force_backend(repo):
    root, base = repo
    assert classify(root, event="workflow_dispatch", base=base).run_backend
    assert scope(root, "").run_backend
    assert scope(root, "missing-ref").run_backend


def test_cli_writes_explicit_github_output_and_summary(repo, tmp_path):
    root, base = repo
    output, summary = tmp_path / "output", tmp_path / "summary"
    script = Path(__file__).resolve().parents[1] / "scripts/ci_change_scope.py"
    subprocess.run([
        os.sys.executable, str(script), "--event", "pull_request", "--base", base, "--repo", str(root),
    ], check=True, capture_output=True, env={**os.environ, "GITHUB_OUTPUT": str(output), "GITHUB_STEP_SUMMARY": str(summary)})
    assert output.read_text() == "run_backend=false\n"
    assert "Markdown" in summary.read_text()


@pytest.mark.parametrize("filename,workflow_name,backend_steps", [
    ("dsl.yml", "DSL compiler", {
        "Install focused DSL dependencies", "Run DSL and touched orchestration contracts", "Check installed-wheel recipe contracts",
    }),
    ("semantic-registry.yml", "Semantic registry", {
        "Install focused test dependencies", "Run semantic core and Lasair live-capture tests", "Validate every provider mapping",
    }),
    ("ui.yml", "Streamlit UI", {"Install focused UI dependencies", "Run offline UI and continuation contracts"}),
])
def test_existing_validate_checks_run_scope_tests_before_conditioning_backend(filename, workflow_name, backend_steps):
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows" / filename).read_text())
    assert workflow["name"] == workflow_name and set(workflow["jobs"]) == {"validate"}
    events = workflow.get("on", workflow.get(True))  # YAML 1.1 treats 'on' as bool.
    paths = events["pull_request"]["paths"]
    assert "**/*.md" in paths
    assert {"scripts/ci_change_scope.py", "tests/test_ci_change_scope.py"} <= set(paths)
    assert "workflow_dispatch" in events
    assert workflow["concurrency"]["cancel-in-progress"] is True
    steps = workflow["jobs"]["validate"]["steps"]
    assert steps[0]["with"]["fetch-depth"] == 0
    tests = next(s for s in steps if s.get("name") == "Verify CI scope contracts")
    classifier = next(s for s in steps if s.get("id") == "scope")
    assert "if" not in tests and "tests/test_ci_change_scope.py" in tests["run"]
    assert steps.index(tests) < steps.index(classifier)
    assert classifier["env"]["CI_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert classifier["env"]["CI_EVENT"] == "${{ github.event_name }}"
    actual_backend = [s for s in steps if s.get("name") in backend_steps]
    assert {s["name"] for s in actual_backend} == backend_steps
    assert all(s["if"] == "steps.scope.outputs.run_backend == 'true'" for s in actual_backend)
    assert all(steps.index(classifier) < steps.index(s) for s in actual_backend)
