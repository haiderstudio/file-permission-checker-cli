```text
examples/bad-script.sh: script is not executable (mode 0644)
examples/noexec: script is not executable (mode 0644)
examples/configs/deploy.sh: script is not executable (mode 0644)
Checked 7 file(s), 3 problem(s) in 3 file(s).
```

Output of `sh examples/run-example.sh` — the checker on the whole
`examples/` folder. It exits 1, because the examples contain
scripts without their executable bit on purpose; the script
itself exits 0.
