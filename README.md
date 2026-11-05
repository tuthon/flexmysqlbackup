# flexmysqlbackup

**Selective MySQL backups, one interactive menu.**

[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](LICENSE)
[![MySQL](https://img.shields.io/badge/MySQL-SQL%20exports-4479A1?logo=mysql&logoColor=white)](https://www.mysql.com/)
[![Bash](https://img.shields.io/badge/Bash-single%20file-4EAA25?logo=gnubash&logoColor=white)](flexmysqlbackup.sh)
[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](src/launcher.py)

Export schemas, table structures, data, views, stored routines, triggers and events. Choose all databases, one database or one object; the launcher handles the MySQL commands and output formatting.

**[Quick start](#quick-start)** · **[Menu](#export-menu)** · **[Full guide](QUICKSTART.md)** · **[Manual commands](docs/MANUAL.md)** · **[Publication](#publication-and-citation)**

> [!NOTE]
> The new launcher is version **1.0.1**. Automated checks cover the client workflow and SQL transformations; installation and restoration on the intended MySQL/NDB versions still need real-server validation. Earlier scripts remain available during this transition.

## Quick start

**1. Download one file.** Open [`flexmysqlbackup.sh`](flexmysqlbackup.sh) and use GitHub's **Download raw file** action. You do not need the rest of the repository to run it.

**2. Start the menu.**

```bash
bash flexmysqlbackup.sh
```

Enter the source host, port, user, password and output directory once. The password is hidden in a terminal. You can run the launcher on your workstation; it does not have to be copied to the database server.

Optional connection arguments:

```bash
bash flexmysqlbackup.sh --host SOURCE_HOST --port 3306 --user YOUR_USER --output ./backups
```

**3. Install generators and export.** On first use, choose **8 → 1** to create `tools` if needed and install all missing generators. A missing generator can also be installed when you select its export option.

Choose an object category and scope. Each export gets a new output directory, and the launcher prints its full path when finished.

## Export menu

| Menu | Objects | Scope and options |
|---|---|---|
| **1** | Schemas | All selected by the generator, or one schema |
| **2** | Table structures | All, one database or one table; engine and target charset/collation |
| **3** | Table data | All, one database or one table; engine filter |
| **4** | Views | All, one database or one view |
| **5** | Procedures and functions | All, one database or one routine; original or transformed SQL |
| **6** | Triggers | All, one database or one trigger |
| **7** | Events | All, one database or one recurring event |
| **8** | Install/update generators | Install missing helpers or explicitly replace all six |
| **0** | Exit | Submenus also provide a Back option |

Definitions are exported as SQL. Table data uses `mysqldump`, with one file per database, the connection you entered and the actual tables matching the engine filter.

The definition-export pipelines retain the original `sed` processing. Routine bodies use escaped MySQL batch output rather than XML, preserving their newlines and SQL escape sequences.

## Requirements

| Component | Purpose |
|---|---|
| Bash | Starts the single-file launcher |
| Python **3.8+** | Menus and transformations; standard library only |
| MySQL client (`mysql`) | Metadata, definitions and generator installation |
| **GNU sed** | Existing definition-export formatting |
| `mysqldump` | Required only for table data |
| Appropriate MySQL privileges | Read selected objects and definitions; create helpers when installing |

The generators use `GET DIAGNOSTICS`, requiring MySQL 5.6 or newer. Validate client compatibility and restored SQL on your intended MySQL/NDB versions.

## Optional routine migration transformations

Menu **5** offers original definitions or the existing `process_sql_opt.sh` transformation engine:

| Transformation | Result |
|---|---|
| Handler bindings `errNom` / `errText` | Use `@errNom` / `@errText`; retain other variables in shared declarations |
| Configured reserved identifiers, such as `over` | Add backticks while preserving handled window-function syntax |
| `REGEXP BINARY` | Keep `REGEXP`; remove the following `BINARY` |
| Supported `utf8` / `utf8mb3` definitions and collations | Convert to `utf8mb4`; retain existing `utf8mb4` definitions |
| `GROUP BY expression DESC` | Remove only `DESC`; add no `ORDER BY` |

Charset conversion covers declarations, parameters, return types and inline `CREATE TABLE` definitions. Strings and comments are protected; dynamic SQL inside strings is not rewritten. Unknown collation mappings stop with an error.

Routine exclusions apply in both modes, including single-routine selection. Defaults exclude the configured copy patterns and names containing five or more digits in total. See [filters and configuration](QUICKSTART.md#routine-migration).

These transformations address specific migration cases; they are not a complete MySQL 8.4 SQL validator.

## Offline tools

Transform an existing UTF-8 file without a database connection:

```bash
bash flexmysqlbackup.sh --transform input.sql output.sql
```

Omit the output path to replace the input atomically after success.

Extract the six embedded generators into one optional installer:

```bash
bash flexmysqlbackup.sh --extract-install-sql install_generators.sql
```

The menu installs helpers directly, using the connected account as their definer and propagating generator errors.

## Restore and compatibility

Restoring exports is a separate step. Restore schemas, table structures and required functions before dependent views and data. Install triggers after importing data if they should not fire during import. Review event schedules before enabling restored events.

Use your actual output filename and target connection:

```bash
mysql --host=TARGET_HOST --port=3306 --user=YOUR_USER --password \
  --default-character-set=utf8mb4 --comments < path/to/export.sql
```

Documented legacy behavior is retained: schema defaults, generator-specific exclusions, table DDL limitations and fixed trigger/event definers inside exported SQL. One-time events are detected and reported instead of silently omitted. Separate data dumps do not provide a coordinated snapshot across databases or NDB tables.

Read the [compatibility guide](QUICKSTART.md#scope-and-inherited-generator-behavior) before replacing an established backup/restore workflow.

## Repository guide

| Path | Purpose |
|---|---|
| [`flexmysqlbackup.sh`](flexmysqlbackup.sh) | Generated standalone distribution; end users only need this file |
| [`QUICKSTART.md`](QUICKSTART.md) | Full menu, installation, configuration and compatibility guide |
| [`src/launcher.py`](src/launcher.py) | Interactive workflow and client handling |
| [`src/transformer.py`](src/transformer.py) | Routine SQL transformations |
| [`src/sql/`](src/sql/) | Maintained SQL inputs embedded by the build |
| [`build.py`](build.py) | Rebuild the standalone Bash file |
| [`tests/`](tests/), [`TESTING.md`](TESTING.md) | Regression tests, validation and remaining server checks |
| [`docs/MANUAL.md`](docs/MANUAL.md) | Earlier manual commands, including the original `sed` pipelines |
| [`process_sql_opt.sh`](process_sql_opt.sh), root `gen_*.sql` | Earlier standalone interfaces retained for compatibility |
| [`figure3.png`](figure3.png), [`figure5.png`](figure5.png) | Original workflow diagrams, linked from the manual |
| [`LICENSE`](LICENSE) | Existing GPL-2.0 license text |

Edit `src/` and run `build.py` to update the distribution. Root `gen_*.sql` files are retained compatibility copies and are not build inputs.

## Development

```bash
python3 build.py
python3 build.py --check
bash -n flexmysqlbackup.sh
python3 -m unittest discover -s tests -v
```

Tests use simulated MySQL clients and real GNU sed/subprocesses. They cover transformations, menus, filters, installation, files and failure handling. They do not execute helper DDL on a real MySQL server. See [TESTING.md](TESTING.md).

For bug reports, include selected options, script/client/server versions and error text. For transformation changes, include a small SQL input and expected output. Keep credentials out of examples and logs.

## Publication and citation

The project accompanies [flexmysqlbackup — Computer Science and Interdisciplinary Research Journal (2025)](https://doi.org/10.70862/CSIR.2025.0201-10).

If this tool contributes to your research, cite the related article using DOI **10.70862/CSIR.2025.0201-10**.

## License and author

The repository contains the [GNU General Public License, version 2](LICENSE). The license file is retained unchanged.

Created by **Dimitar Todorov** · [GitHub](https://github.com/tuthon) · [Email](mailto:tuthon@gmail.com)
