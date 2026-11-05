# flexmysqlbackup — interactive launcher

One downloadable Bash file provides menus, installs the SQL generators and exports SQL files. The SQL generators and the existing `process_sql_opt.sh` transformation engine are embedded in `flexmysqlbackup.sh`. No GitHub downloads occur while it runs.

## Start

Download **flexmysqlbackup.sh**, open a terminal in its directory, and run:

```bash
bash flexmysqlbackup.sh
```

Enter the MySQL host, port, user, password and output directory once. The password is hidden when running in a terminal. The script can run on a workstation with the MySQL client installed; it does not have to run on the database server.

Optional connection arguments:

```bash
bash flexmysqlbackup.sh --host SOURCE_HOST --port 3306 --user devops --output ./backups
```

The password is still prompted interactively. It is not stored in the script or generated files, and is not passed as a command-line argument. Child MySQL processes receive it through `MYSQL_PWD`, following the existing script's connection method. `--no-defaults` and `MYSQL_TEST_LOGIN_FILE=/dev/null` prevent saved settings from overriding this connection.

## Requirements

- Bash and Python **3.8+** (standard library only).
- MySQL command-line client, `mysql`.
- **GNU sed**, as used by the existing export commands.
- `mysqldump`, only for table data.
- Access to the requested objects and their definitions on the source server.

On Ubuntu/Debian, these tools are normally installed with:

```bash
sudo apt install bash python3 default-mysql-client sed
```

Use a client version compatible with your source server. The legacy generators use `GET DIAGNOSTICS`, requiring MySQL 5.6 or newer. This new launcher has automated fixture tests; installation and restoration still need validation on your actual MySQL/NDB versions.

## Main menu

| Option | Action | Selections |
|---|---|---|
| 1 | Export schemas | All schemas selected by the generator, or one schema |
| 2 | Export table structures | All, one database, one table; optional engine filter and target charset/collation |
| 3 | Export table data | All, one database, one table; optional engine filter |
| 4 | Export views | All, one database, one view |
| 5 | Export procedures and functions | All, one database, one routine; original or transformed definitions |
| 6 | Export triggers | All, one database, one trigger |
| 7 | Export events | All, one database, one event |
| 8 | Install/update generators | Install missing generators, or replace all six bundled generators |
| 0 | Exit | — |

Submenus have **0. Back**. After an operation, the main menu appears again. MySQL commands and `sed` processing are handled internally.

### First use and installation

If a selected generator is missing, the script offers to install it in the **tools** database. Alternatively, choose **8 → 1** to install all missing generators together.

Installation executes `CREATE DATABASE IF NOT EXISTS tools` and creates the selected helper procedures. It requires the relevant database/routine creation privileges. Existing helpers are retained unless you choose **8 → 2**, confirm replacement, and update them explicitly.

The installer only manages these six procedures:

```text
tools.gen_schemes_script
tools.gen_table_script
tools.gen_data_script
tools.gen_view_script
tools.gen_triggers_script
tools.gen_event_script
```

Bundled helper adaptations:

- Helper procedures use `DEFINER=CURRENT_USER`, avoiding the original fixed installation account.
- Helper declarations use `utf8mb4`; the long `SchemaNames VARCHAR(21845)` declaration becomes `TEXT` because four-byte characters exceed the VARCHAR byte limit.
- Helper exception handlers use `RESIGNAL` after diagnostics so a failed generator is reported as a failure, rather than saved as SQL.
- Helper procedures are created under session SQL mode `NO_ENGINE_SUBSTITUTION`, matching their legacy SQL syntax. The installation session's previous mode is restored afterwards; no global server setting is changed.

Updating uses `DROP PROCEDURE` followed by `CREATE PROCEDURE`. These operations are not transactional: if an update fails, correct the reported error and rerun installation for the missing helper.

### Table structures and character sets

Leave both target settings blank to preserve the source definitions. To change them, enter a compatible pair such as:

```text
Target character set: utf8mb4
Target collation: utf8mb4_general_ci
```

These are **target values**, not an old/new replacement pair. The launcher validates the pair against the source server. This setting is separate from the routine migration transformations.

### Routine migration

Option **5** offers:

1. **Apply process_sql_opt migration transformations** — reuse the existing transformation engine.
2. **Export original definitions** — retain the original routine body.

Both modes apply the configurable routine exclusions. The transformed mode:

- Replaces handler bindings `errNom`/`errText` with `@errNom`/`@errText` and removes their corresponding local declarations while retaining other declared variables.
- Converts supported `utf8`/`utf8mb3` declarations, collations and inline `CREATE TABLE` definitions to `utf8mb4`, preserving existing `utf8mb4` definitions.
- Quotes configured identifiers, such as `over`, while retaining genuine window function syntax.
- Changes `REGEXP BINARY` to `REGEXP`.
- Removes **only `DESC` modifiers in `GROUP BY`**. It adds no `ORDER BY`, and leaves existing `ORDER BY` clauses alone.

SQL strings and comments are protected by the tokenizer. Dynamically constructed SQL inside string literals is not rewritten. Unknown collation mappings and invalid UTF-8 stop the export rather than silently replacing text. These transformations do not provide a complete MySQL 8.4 compatibility check.

Defaults near the beginning of the Bash file can be edited or overridden with environment variables:

```bash
# Allow routine names containing five or more digits.
MAX_DIGITS_IN_NAME=0 bash flexmysqlbackup.sh

# Disable name-pattern exclusions.
EXCLUDE_SP_PATTERNS_JSON='[]' bash flexmysqlbackup.sh

# Exclude additional databases from routine exports.
EXCLUDED_SCHEMAS_JSON='["test","backup"]' bash flexmysqlbackup.sh
```

Default name patterns: `%copy`, `%copy1`, `%copy2`, `%copy3`, `alter_table`, `%transfer_casino_balance_shard%`. `%` and `_` follow SQL `LIKE` semantics. The default digit limit is **5 or more digits total**, including digits separated by date punctuation.

### Table data

Data export uses `mysqldump` with the original generator's core data-only flags. It reads the selected tables from metadata, uses the current connection, and creates one file per database. This avoids executing generated shell commands containing fixed credentials, and makes the engine filter apply to the actual tables being dumped.

`--column-statistics=0` is added only if the installed dump client supports it. When particular tables are selected, the launcher passes `database table...` without `--databases`, because that option would interpret table arguments as database names.

Data files contain `USE database;` followed by data statements. Restore schemas and table structures before these files. Separate dumps are not a coordinated snapshot across databases or NDB tables; the launcher retains the legacy dump consistency behavior.

## Output

Every operation creates a new directory under the chosen output directory:

```text
backups/source_YYYYMMDD_HHMMSS_category_unique-suffix/
```

The result is `schemas.sql`, `tables.sql`, `views.sql`, `routines.sql`, `triggers.sql`, `events.sql`, or a set of `database_data.sql` files. Repeated exports create separate directories, preventing accidental appending or overwriting. New directories and SQL files are accessible only to the current OS user by default.

Definition exports retain `sed '1d'` to remove the result heading. Version **1.0.2** then decodes the complete batch field exactly once, restoring tabs, newlines, NUL and backslashes. This replaces the earlier newline-only conversion, which could leave literal `\t` outside SQL strings and trigger MySQL client commands during import.

```bash
# Header removal, followed internally by complete batch-field decoding
mysql ... | sed '1d'
```

Routine definitions are read from `SHOW CREATE` using the client's escaped `--batch` output. The launcher separates fields first, then decodes exactly one layer of MySQL escaping for newlines, tabs, NUL and backslashes. Literal SQL escape sequences, Unicode and control characters are retained. XML output is not used.

Version **1.0.1** removes the XML dependency introduced in 1.0.0 and adds errors that identify the routine/list being read. Existing generators do not need to be reinstalled for this client-side update.

Version **1.0.2** applies complete escape decoding to generator output too, including events, views, triggers and table structures. Replace the launcher and re-export affected definitions; no generator reinstallation is required. The manual guide retains the earlier pipelines for reference, but newline-only `sed` conversion is unsuitable for bodies containing tabs or escaped SQL strings.

## Offline operations

Transform an existing UTF-8 SQL file without a MySQL connection, password or menu:

```bash
bash flexmysqlbackup.sh --transform input.sql output.sql
```

Omit `output.sql` to replace the input atomically after a successful transformation.

Extract all six helper definitions into one installer SQL file:

```bash
bash flexmysqlbackup.sh --extract-install-sql install_generators.sql
```

Extraction refuses to overwrite an existing installer file. The interactive installation menu runs the embedded installer directly, so this manual step is optional.

## Scope and inherited generator behavior

This is an installer/menu wrapper around the existing project, not a redesign of every SQL generator. Generator-specific schema exclusions and generated DDL behavior are retained. In particular:

- The schema generator assigns `utf8mb4`/`utf8mb4_general_ci`, as before.
- The trigger/event generators retain their legacy fixed DEFINER **inside exported SQL**. This differs from the installer, which uses the connected user for the helper procedures themselves.
- The legacy event generator constructs recurring event schedules. If matching one-time events exist, the launcher stops and lists them rather than silently omitting them. Those events require separate export.
- The legacy table generator has limitations for unusual identifiers and some newer DDL features. The launcher rejects ambiguous comma-separated table names and unsafe schema filters instead of feeding them into its dynamic SQL.
- Legacy `GROUP_CONCAT` size limits and original `sed` escaping behavior are retained.

Inspect exported SQL and test restoration on your destination server, particularly during a 5.6 → 8.4 migration. The launcher itself only installs helper procedures and creates local export files; it does not restore the exported application objects.

## Development and validation

The source archive includes modular SQL, the launcher, the transformation engine and tests. End users only need the generated **flexmysqlbackup.sh**.

```bash
python3 build.py
python3 build.py --check
bash -n flexmysqlbackup.sh
python3 -m unittest discover -s tests -v
```

The tests cover the inherited transformation cases, every export menu, actual GNU sed processing, connection arguments, missing-helper installation, explicit updates, engine-filtered dumps, Unicode, output isolation and failure cleanup. Database clients are simulated for integration tests: they do not establish MySQL connections or prove server-side DDL compatibility.

The project is based on [tuthon/flexmysqlbackup](https://github.com/tuthon/flexmysqlbackup). Keep the upstream GPL-2.0 license when distributing this addition.
