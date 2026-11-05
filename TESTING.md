# Validation of the interactive launcher

Validated on 2026-11-05 with Python 3.12, Bash and GNU sed.

```text
bash -n flexmysqlbackup.sh
Passed

python3 -m unittest discover -s tests -v
Ran 76 tests
OK
```

- 46 regression tests for the inherited SQL transformation engine.
- 29 launcher/integration/parser tests using simulated MySQL clients and real subprocesses/GNU sed.
- 1 distribution check verifies that the standalone Bash file matches its modular sources.
- Every object category is exercised, including a procedure and a function.
- Tests cover missing-helper installation, explicit replacement, declined installation, connection and query failures, inherited diagnostic result sets, failed data dumps, UTF-8 errors, exclusion configuration, offline operation and file permissions.
- The distribution is built from the included sources; tests invoke the actual generated Bash file.
- Version 1.0.1 regressions cover empty results, malformed rows, expected column names, literal SQL escape sequences and routine bodies containing Unicode, tabs, CR, NUL and XML-forbidden control characters. Original routine bodies round-trip byte for byte; transformed bodies retain all content outside the requested changes. No query uses XML output.

The simulated clients do **not** parse or execute stored-procedure DDL. No source or destination database was contacted. Starting a disposable MySQL server was unavailable because local socket creation was denied in the execution environment. The bundled installer and restored exports must therefore be validated on the intended MySQL/NDB versions before treating this launcher as a replacement for the existing workflow.

Suggested first server check:

1. Run the launcher against a test MySQL server.
2. Select **8 → 1** to install missing generators.
3. Export one known schema, one table structure and its data, one view, one routine, one trigger and one recurring event.
4. Compare against the previous export commands and restore to a disposable destination.
5. Then try wider database/all-object selections.
