"""Tests for file-permission-checker-cli. Standard library only."""

import ast
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src" / "file_permission_checker.py"

sys.path.insert(0, str(ROOT / "src"))
import file_permission_checker as fpc
from file_permission_checker import (
    Problem, check_file, collect, has_shebang, is_script, mode_string,
)

IS_ROOT = os.geteuid() == 0


def run_cli(*args, cwd=None):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        capture_output=True, text=True, cwd=cwd or str(ROOT))


def make_file(root, name, content="", mode=0o644):
    path = Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    os.chmod(path, mode)
    return path


class ModeStringTests(unittest.TestCase):
    def test_world_writable(self):
        self.assertEqual(mode_string(0o100666), "0666")

    def test_executable(self):
        self.assertEqual(mode_string(0o100755), "0755")

    def test_plain(self):
        self.assertEqual(mode_string(0o100644), "0644")

    def test_directory_mode_ignored(self):
        # Only the permission bits are shown, not the file type.
        self.assertEqual(mode_string(0o40777), "0777")


class ShebangTests(unittest.TestCase):
    def test_shebang_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool", "#!/bin/sh\necho hi\n")
            self.assertTrue(has_shebang(path))

    def test_no_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool", "echo hi\n")
            self.assertFalse(has_shebang(path))

    def test_shebang_on_second_line_not_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool", "\n#!/bin/sh\n")
            self.assertFalse(has_shebang(path))

    def test_empty_file_has_no_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool", "")
            self.assertFalse(has_shebang(path))

    def test_sh_extension_is_script_without_shebang(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "plain.sh", "echo hi\n")
            self.assertTrue(is_script(path))

    def test_uppercase_sh_extension_is_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "plain.SH", "echo hi\n")
            self.assertTrue(is_script(path))

    def test_txt_with_shebang_is_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool.txt", "#!/bin/sh\necho hi\n")
            self.assertTrue(is_script(path))

    def test_plain_txt_is_not_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "notes.txt", "hello\n")
            self.assertFalse(is_script(path))


class CheckFileTests(unittest.TestCase):
    def test_clean_text_file_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "notes.txt", "hello\n", 0o644)
            self.assertEqual(check_file(path), [])

    def test_executable_script_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "run.sh", "#!/bin/sh\necho hi\n", 0o755)
            self.assertEqual(check_file(path), [])

    def test_world_writable_flagged_with_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "shared.txt", "hello\n", 0o666)
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].text(),
                             f"{path}: world-writable (mode 0666)")

    def test_world_writable_directory_mode_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "shared.txt", "hello\n", 0o777)
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("world-writable (mode 0777)", found[0].reason)

    def test_group_writable_only_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "shared.txt", "hello\n", 0o664)
            self.assertEqual(check_file(path), [])

    def test_sh_script_missing_exec_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "run.sh", "#!/bin/sh\necho hi\n", 0o644)
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0].text(),
                             f"{path}: script is not executable (mode 0644)")

    def test_shebang_file_missing_exec_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "tool", "#!/usr/bin/env python3\n", 0o644)
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("script is not executable", found[0].reason)

    def test_sh_without_shebang_still_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "plain.sh", "echo hi\n", 0o644)
            self.assertEqual(len(check_file(path)), 1)

    def test_owner_exec_bit_is_what_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Group-only execute: the owner still cannot run it.
            path = make_file(tmp, "run.sh", "#!/bin/sh\n", 0o010)
            self.assertEqual(len(check_file(path)), 1)
            path2 = make_file(tmp, "run2.sh", "#!/bin/sh\n", 0o111)
            self.assertEqual(check_file(path2), [])

    def test_world_writable_script_reports_both_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_file(tmp, "run.sh", "#!/bin/sh\n", 0o666)
            found = check_file(path)
            self.assertEqual(len(found), 2)
            self.assertIn("world-writable", found[0].reason)
            self.assertIn("not executable", found[1].reason)

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = check_file(Path(tmp) / "gone.txt")
            self.assertEqual(len(found), 1)
            self.assertIn("cannot check file", found[0].reason)

    @unittest.skipIf(IS_ROOT, "root can read any file, so no read failure")
    def test_unreadable_file_still_mode_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Write-only for others: mode check works, shebang read fails.
            path = make_file(tmp, "locked", "#!/bin/sh\n", 0o002)
            found = check_file(path)
            self.assertEqual(len(found), 1)
            self.assertIn("world-writable (mode 0002)", found[0].reason)


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_checks_every_file(self):
        make_file(self.root, "a.txt", "hi\n", 0o644)
        make_file(self.root, "b.sh", "#!/bin/sh\n", 0o644)
        make_file(self.root, "c.md", "hi\n", 0o666)
        checked, problems = collect([self.root])
        self.assertEqual({p.name for p in checked},
                         {"a.txt", "b.sh", "c.md"})
        self.assertEqual(len(problems), 2)

    def test_file_given_directly_checked_whatever_its_name(self):
        path = make_file(self.root, "weird.dat", "#!/bin/sh\n", 0o644)
        checked, problems = collect([path])
        self.assertEqual(checked, [path])
        self.assertEqual(len(problems), 1)

    def test_git_folder_never_walked(self):
        git = self.root / ".git"
        git.mkdir()
        make_file(git, "bad.sh", "#!/bin/sh\n", 0o644)
        make_file(self.root, "a.txt", "hi\n", 0o644)
        checked, problems = collect([self.root])
        self.assertEqual([p.name for p in checked], ["a.txt"])
        self.assertEqual(problems, [])

    def test_no_recursive_stops_at_top_level(self):
        make_file(self.root, "a.txt", "hi\n", 0o644)
        make_file(self.root, "sub/b.sh", "#!/bin/sh\n", 0o644)
        checked, problems = collect([self.root], recursive=False)
        self.assertEqual([p.name for p in checked], ["a.txt"])
        self.assertEqual(problems, [])

    def test_exclude_skips_matching_files(self):
        make_file(self.root, "a.sh", "#!/bin/sh\n", 0o644)
        make_file(self.root, "b.sh", "#!/bin/sh\n", 0o644)
        checked, problems = collect([self.root], exclude=["b.sh"])
        self.assertEqual([p.name for p in checked], ["a.sh"])
        self.assertEqual(len(problems), 1)

    def test_exclude_skips_matching_folders(self):
        make_file(self.root, "vendor/bad.sh", "#!/bin/sh\n", 0o644)
        make_file(self.root, "a.txt", "hi\n", 0o644)
        checked, problems = collect([self.root], exclude=["vendor"])
        self.assertEqual([p.name for p in checked], ["a.txt"])
        self.assertEqual(problems, [])

    def test_missing_path_reported(self):
        checked, problems = collect([self.root / "missing.txt"])
        self.assertEqual(checked, [])
        self.assertEqual(len(problems), 1)
        self.assertIn("no such file or folder", problems[0].reason)

    def test_symlink_to_script_checked_by_target_mode(self):
        target = make_file(self.root, "real.sh", "#!/bin/sh\n", 0o644)
        link = self.root / "link.sh"
        os.symlink(target, link)
        checked, problems = collect([link])
        self.assertEqual(len(problems), 1)
        self.assertIn("not executable", problems[0].reason)


class CliTests(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        result = run_cli("examples/good.sh")
        self.assertEqual(result.returncode, 0)
        self.assertIn("all file permissions are sane", result.stdout)

    def test_bad_file_exit_one(self):
        result = run_cli("examples/bad-script.sh")
        self.assertEqual(result.returncode, 1)
        self.assertIn("1 problem(s)", result.stdout)

    def test_no_args_exit_two(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)

    def test_json_output(self):
        result = run_cli("examples/noexec", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["files_checked"], 1)
        self.assertEqual(data["files_with_problems"], 1)
        self.assertEqual(len(data["problems"]), 1)
        self.assertEqual(data["problems"][0]["file"], "examples/noexec")
        self.assertIn("not executable", data["problems"][0]["reason"])
        self.assertNotIn("line", data["problems"][0])
        self.assertIn("examples/noexec: script is not executable",
                      result.stderr)

    def test_json_clean(self):
        result = run_cli("examples/good.sh", "--json")
        self.assertEqual(result.returncode, 0)
        data = json.loads(result.stdout)
        self.assertEqual(data["problems"], [])
        self.assertEqual(data["files_with_problems"], 0)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("1.0.0", result.stdout)

    def test_folder_run(self):
        result = run_cli("examples")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 7 file(s), 3 problem(s) in 3 file(s).",
                      result.stdout)


class ExampleTests(unittest.TestCase):
    def test_sample_output_matches_fresh_run(self):
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        result = run_cli("examples")
        self.assertEqual(result.stdout, block)

    def test_run_example_script(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)
        expected = (ROOT / "examples" / "sample-output.md").read_text()
        block = re.search(r"```text\n(.*?)```", expected, re.S).group(1)
        self.assertEqual(result.stdout, block)

    def test_good_examples_pass(self):
        for name in ("examples/good.sh", "examples/good.txt"):
            result = run_cli(name)
            self.assertEqual(result.returncode, 0, name)

    def test_bad_examples_fail(self):
        for name in ("examples/bad-script.sh", "examples/noexec",
                     "examples/configs/deploy.sh"):
            result = run_cli(name)
            self.assertEqual(result.returncode, 1, name)
            self.assertIn("1 problem(s)", result.stdout, name)

    def test_example_modes_are_as_documented(self):
        self.assertEqual(stat.S_IMODE(os.stat(
            ROOT / "examples/good.sh").st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(os.stat(
            ROOT / "examples/bad-script.sh").st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(
            ROOT / "examples/noexec").st_mode), 0o644)
        self.assertEqual(stat.S_IMODE(os.stat(
            ROOT / "examples/configs/deploy.sh").st_mode), 0o644)


class ReadmeTests(unittest.TestCase):
    DEMO = Path("/tmp/perm-demo")

    def build_demo(self):
        if self.DEMO.exists():
            shutil.rmtree(self.DEMO)
        self.DEMO.mkdir(parents=True)
        shutil.copy(ROOT / "examples/good.txt",
                    self.DEMO / "shared.txt")
        os.chmod(self.DEMO / "shared.txt", 0o666)

    def test_text_blocks_match_live_output(self):
        readme = (ROOT / "README.md").read_text()
        blocks = re.findall(r"```text\n(.*?)```", readme, re.S)
        self.assertTrue(blocks, "no ```text blocks found in README")
        self.build_demo()
        try:
            live = []
            live.append(run_cli("examples/good.sh").stdout)
            live.append(run_cli("examples/bad-script.sh").stdout)
            live.append(run_cli("examples").stdout)
            live.append(run_cli(str(self.DEMO)).stdout)
            joined = "\n".join(live)
            for block in blocks:
                self.assertIn(block.strip(), joined,
                              "README text block not in live output")
        finally:
            shutil.rmtree(self.DEMO, ignore_errors=True)

    def test_json_block_matches_live_output(self):
        readme = (ROOT / "README.md").read_text()
        match = re.search(r"```json\n(.*?)```", readme, re.S)
        self.assertIsNotNone(match, "no ```json block found in README")
        result = run_cli("examples/noexec", "--json")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(match.group(1)),
                         json.loads(result.stdout))


class HygieneTests(unittest.TestCase):
    BANNED = ("TODO", "FIXME", "coming soon", "lorem", "placeholder")

    def test_no_banned_words_in_repo(self):
        hits = []
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            for word in self.BANNED:
                if word in text:
                    hits.append(f"{path.relative_to(ROOT)}: {word}")
        self.assertEqual(hits, [])

    def test_no_third_party_imports(self):
        tree = ast.parse(SRC.read_text())
        stdlib = set(sys.stdlib_module_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name.split(".")[0], stdlib)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module.split(".")[0], stdlib)

    def test_gitignore_first_line_is_env(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_license_present(self):
        self.assertTrue((ROOT / "LICENSE").exists())
        self.assertIn("MIT License", (ROOT / "LICENSE").read_text())

    def test_ci_file_present_and_runs_tests(self):
        ci = ROOT / ".github" / "workflows" / "ci.yml"
        self.assertTrue(ci.exists())
        text = ci.read_text()
        self.assertIn("python3 tests/test_file_permission_checker.py", text)
        self.assertIn("actions/checkout", text)
        self.assertIn("push", text)
        self.assertIn("pull_request", text)

    def test_no_absolute_local_paths(self):
        home = str(Path.home())
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            parts = path.relative_to(ROOT).parts
            if ".git" in parts or "__pycache__" in parts:
                continue
            if "tests" in parts:
                continue
            text = path.read_bytes().decode("utf-8", errors="ignore")
            self.assertNotIn(home, text, str(path))

    def test_readme_names_what_it_does_not_do(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("does NOT do", readme)
        self.assertIn("never changes a permission", readme)

    def test_checker_passes_on_own_code(self):
        # The tool's own code must be clean: every script in src/
        # and tests/ is executable or not a script at all, and
        # nothing is world-writable. (The examples/ folder is
        # deliberately dirty and is checked separately.)
        for subdir in ("src", "tests"):
            result = run_cli(str(ROOT / subdir))
            self.assertEqual(result.returncode, 0,
                             f"{subdir}: {result.stdout}")


if __name__ == "__main__":
    unittest.main()
