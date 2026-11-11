"""file-permission-checker-cli: check files in a folder have sane permissions, fail CI when they do not.

Reads one or more files (or folders of them), checks every file
for two problems, and reports each one with the file and its mode.
Report-only: it never changes a permission. Exit 0 when every
file is clean, 1 when any problem is found, 2 for a usage error.

The two checks, both from the Python standard library
(`os.stat` and the `stat` module):

- World-writable: any file other people can write to (mode
  with the 002 bit set, such as 0666 or 0777) is a security
  hole in a shared repo. It is reported as
  "world-writable (mode 0666)".
- Script not executable: a script — a `.sh` file, or any file
  whose first line starts with `#!` — that has no owner
  execute bit will fail in CI with "permission denied" after
  working fine on the author's machine, usually because the
  author ran it with `sh script.sh` and never noticed. It is
  reported as "script is not executable (mode 0644)".

A file that is both world-writable and a non-executable script
is reported twice, once for each problem. A file given directly
on the command line is always checked, whatever its name. A
folder is walked for every file in it, recursively by default
(`--no-recursive` stops at the top level). `.git` folders are
never walked, and directory links are never followed.
`--exclude` skips files and folders by name pattern.

What it does not do: it does not check directories — only
files. It does not check whether a script's shebang names an
interpreter that exists (that is what shell-shebang-checker-cli
does). It does not check file ownership. It never touches the
network, and it never changes anything.
"""

import argparse
import fnmatch
import json
import os
import stat
import sys
from pathlib import Path

__version__ = "1.0.0"


class Problem:
    """One problem in one file: path and plain reason.

    Permission problems have no line number — the whole file
    is the problem — so there is none to report.
    """

    def __init__(self, path, reason):
        self.path = path
        self.reason = reason

    def text(self):
        return f"{self.path}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "reason": self.reason}


def mode_string(mode):
    """The permission bits of a mode as a four-digit octal string."""
    return format(stat.S_IMODE(mode), "04o")


def has_shebang(path):
    """True when the file's first two bytes are `#!`.

    A file that cannot be read is treated as having no shebang:
    its permissions are still checked from its mode, which does
    not need a read.
    """
    try:
        with open(path, "rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


def is_script(path):
    """True when the file is a script: a `.sh` file, or a `#!` first line."""
    if path.name.lower().endswith(".sh"):
        return True
    return has_shebang(path)


def check_file(path):
    """Check one file and return its problems."""
    label = str(path)
    try:
        info = os.stat(path)
    except OSError as exc:
        return [Problem(label, f"cannot check file: {exc.strerror or exc}")]
    mode = stat.S_IMODE(info.st_mode)
    problems = []
    if mode & 0o002:
        problems.append(Problem(
            label, f"world-writable (mode {mode_string(mode)})"))
    if is_script(path) and not mode & 0o100:
        problems.append(Problem(
            label, f"script is not executable (mode {mode_string(mode)})"))
    return problems


def collect(paths, recursive=True, exclude=()):
    """Gather the files to check and their problems.

    A file given directly is always checked, whatever its name. A
    folder is walked for every file in it, recursively by default.
    `.git` folders are never walked, and directory links are never
    followed.
    """
    checked = []
    problems = []
    for given in paths:
        path = Path(given)
        if path.is_file():
            checked.append(path)
            problems.extend(check_file(path))
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs
                                 if d != ".git"
                                 and not any(fnmatch.fnmatch(d, pat)
                                             for pat in exclude))
                for name in sorted(files):
                    candidate = Path(root) / name
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    checked.append(candidate)
                    problems.extend(check_file(candidate))
                if not recursive:
                    break
        else:
            problems.append(Problem(str(given), "no such file or folder"))
    return checked, problems


def main(argv=None):
    """Entry point. Returns the exit code: 0 clean, 1 problems, 2 usage."""
    parser = argparse.ArgumentParser(
        prog="file_permission_checker",
        description="Check files in a folder have sane permissions.")
    parser.add_argument("paths", nargs="*", metavar="PATH",
                        help="file or folder to check")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON (human lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders matching this name pattern")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    if not args.paths:
        parser.error("give at least one file or folder")
    checked, problems = collect(args.paths,
                                recursive=not args.no_recursive,
                                exclude=args.exclude)

    files_with_problems = len({p.path for p in problems})
    if args.json:
        result = {
            "files_checked": len(checked),
            "problems": [p.as_dict() for p in problems],
            "files_with_problems": files_with_problems,
        }
        print(json.dumps(result, indent=2))
        for problem in problems:
            print(problem.text(), file=sys.stderr)
    else:
        for problem in problems:
            print(problem.text())
        if problems:
            print(f"Checked {len(checked)} file(s), "
                  f"{len(problems)} problem(s) in {files_with_problems} file(s).")
        else:
            print(f"OK — {len(checked)} file(s) checked, "
                  f"all file permissions are sane.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
