# file-permission-checker-cli

Check files in a folder have sane permissions, fail CI when a world-writable file or a script without its executable bit slips in.

[![CI](https://github.com/haiderstudio/file-permission-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/file-permission-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`file_permission_checker` reads the files in a folder (or
files given directly) and checks every one for two problems,
reporting each with the file and its mode. It exits 1 when
any problem is found, so it can fail a CI run. A clean folder
exits 0.

- **World-writable files.** Any file other people can write
  to (mode with the 002 bit set, such as 0666 or 0777) is a
  security hole in a shared repo. It is reported as
  `world-writable (mode 0666)`.
- **Scripts without their executable bit.** A script — a
  `.sh` file, or any file whose first line starts with `#!`
  — with no owner execute bit fails in CI with "permission
  denied" after working fine on the author's machine, usually
  because the author ran it with `sh script.sh` and never
  noticed. It is reported as
  `script is not executable (mode 0644)`.
- A file that is both world-writable and a non-executable
  script is reported twice, once for each problem. Every
  problem is reported, not just the first.
- A file given directly on the command line is always
  checked, whatever its name. A folder is walked for every
  file in it, recursively by default (`--no-recursive` stops
  at the top level). `.git` folders are never walked, and
  directory links are never followed. `--exclude` skips files
  and folders by name pattern — useful for a `.sh` file that
  is only ever sourced and never meant to run.
- `--json` prints the result as JSON (the human-readable lines
  go to standard error).

## Who it is for

Anyone shipping scripts — developers whose CI runs shell
scripts, deploy scripts, and hooks, and anyone who has
watched a deploy fail with "permission denied" on a script
that worked fine on their own machine. A world-writable
file in a repo is a security hole, and a script without its
executable bit is a broken deploy waiting to happen.

## What it does NOT do

- It does not check directories — only files. A
  world-writable folder is not reported.
- It does not check whether a script's shebang names an
  interpreter that exists. That is what
  shell-shebang-checker-cli does; this tool only checks the
  executable bit.
- It does not check file ownership, or whether a file should
  be executable in the first place — a `.sh` file that is
  only ever sourced will be reported, and `--exclude` is the
  way to leave it out.
- It does not convert or rewrite anything. It is report-only,
  it never changes a permission, and it never touches the
  network.

## How this differs

- A GitHub search for `"file-permission-checker-cli"` returns
  0 results, and a search for `file permission checker`
  returns 53 results (checked Nov 10, 2026). Top:
  legionus/osec, 6 stars — "Lightweight file permission
  checker", a Linux system-security tool that audits OS
  files, a different job from a repo CI gate;
  rangercha/S3PublicPermsChecker, 3 stars — checks S3
  buckets, a different job; KaiQTang/filePermissionChecker,
  0 stars — lists permissions to a CSV for analysis, a
  reporter, not a checker with a fail/CI gate. No rival is a
  repo CI gate for file permissions.
- Repo #64 (shell-shebang-checker-cli) checks a script's
  shebang line; this checks the file's permission bits — a
  different check on the same scripts.

## How it works

The checker reads each file's mode with `os.stat` and the
`stat` module — nothing else. The 002 bit means
world-writable; the 100 bit means the owner can execute it.
A file is a script when its name ends in `.sh` or its first
two bytes are `#!`. That is the whole check: no parsing, no
guessing, and the mode is printed in the report, so the fix
is obvious (`chmod +x` for a script, `chmod o-w` for a
world-writable file).

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/file-permission-checker-cli.git
cd file-permission-checker-cli
```

## Usage

Check one clean file:

```sh
python3 src/file_permission_checker.py examples/good.sh
```

```text
OK — 1 file(s) checked, all file permissions are sane.
```

Check one script without its executable bit:

```sh
python3 src/file_permission_checker.py examples/bad-script.sh
```

```text
examples/bad-script.sh: script is not executable (mode 0644)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check a whole folder:

```sh
python3 src/file_permission_checker.py examples
```

```text
examples/bad-script.sh: script is not executable (mode 0644)
examples/noexec: script is not executable (mode 0644)
examples/configs/deploy.sh: script is not executable (mode 0644)
Checked 7 file(s), 3 problem(s) in 3 file(s).
```

Catch a world-writable file:

```sh
mkdir -p /tmp/perm-demo
cp examples/good.txt /tmp/perm-demo/shared.txt
chmod 666 /tmp/perm-demo/shared.txt
python3 src/file_permission_checker.py /tmp/perm-demo
```

```text
/tmp/perm-demo/shared.txt: world-writable (mode 0666)
Checked 1 file(s), 1 problem(s) in 1 file(s).
```

Machine-readable output:

```sh
python3 src/file_permission_checker.py examples/noexec --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/noexec",
      "reason": "script is not executable (mode 0644)"
    }
  ],
  "files_with_problems": 1
}
```

## Examples

- `examples/good.sh` — a script with its executable bit
  (mode 0755). Passes.
- `examples/good.txt` — a plain file with sane permissions
  (mode 0644). Passes.
- `examples/bad-script.sh` — a `.sh` script without its
  executable bit (mode 0644). Fails with exit 1.
- `examples/noexec` — a file with a `#!` first line and no
  `.sh` name, without its executable bit (mode 0644). Fails
  with exit 1.
- `examples/configs/deploy.sh` — the same problem, in a
  subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_file_permission_checker.py
```

The tests cover: mode formatting (0666, 0755, 0644, 0777),
shebang detection (first line, second line, empty file,
`.sh` with no shebang, uppercase `.SH`, `#!` in a `.txt`
file), clean files (plain file, executable script,
group-writable only), world-writable files (0666, 0777, a
file that is both world-writable and a non-executable
script reporting both problems), scripts missing the
executable bit (`.sh`, shebang file, `.sh` with no shebang,
group-only execute vs owner execute), missing and unreadable
files, folder walking (every file, `.git` skipped,
`--no-recursive`, `--exclude` for files and folders, direct
files, missing paths, symlinks), exit codes 0/1/2, `--json`,
`--version`, and the bundled examples (the sample output is
compared byte-for-byte against a fresh run, the example file
modes are checked, and the outputs quoted in this README
are checked against real runs).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The check
is two permission bits read with the standard library; the
code, the wording, and the tests are original. The
shebang-detection idea is shared with repo #64
(shell-shebang-checker-cli), which checks the shebang line
itself — this repo checks the permission bits, a different
job on the same scripts.
