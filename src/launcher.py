"""Interactive client. Resources are injected by build.py; Python standard library only."""
import argparse
import collections
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

VERSION = '1.0.2'
SYSTEM_SCHEMAS = ('mysql', 'information_schema', 'performance_schema', 'ndbinfo', 'ndbmemcache', 'sys')
GENERATORS = ('gen_schemes_script', 'gen_table_script', 'gen_data_script',
              'gen_view_script', 'gen_triggers_script', 'gen_event_script')
DEFAULT_PATTERNS = ['%copy', '%copy1', '%copy2', '%copy3', 'alter_table', '%transfer_casino_balance_shard%']
RESOURCES = {}  # Injected into the distributable; never downloaded at runtime.


class BackupError(Exception):
    pass


def decode_batch_field(value):
    """Undo exactly one layer of mysql --batch escaping, retaining SQL escapes."""
    escapes = {'n': '\n', 't': '\t', '0': '\0', '\\': '\\'}
    return re.sub(r'\\([nt0\\])', lambda m: escapes[m[1]], value)


def parse_batch_rows(text, context, required_columns=()):
    """Decode mysql --batch fields, without treating SQL text as XML or Python escapes.

    The client escapes LF, TAB, NUL and backslash. A literal SQL \\n arrives as
    \\\\n, so only one decoding pass is correct. CR and other control characters
    can remain literal: split on LF only, never str.splitlines().
    """
    if not text:
        return []
    lines = text.split('\n')
    if lines[-1] == '':
        lines.pop()
    headers = lines[0].split('\t')
    if not all(headers) or len(set(headers)) != len(headers):
        raise BackupError(f'{context}: invalid column headers from mysql --batch.')
    missing = set(required_columns) - set(headers)
    if missing:
        raise BackupError(f'{context}: mysql --batch did not return expected columns: '
                          + ', '.join(sorted(missing)) + '. Export stopped.')
    result = []
    for number, line in enumerate(lines[1:], start=1):
        fields = line.split('\t')
        if len(fields) != len(headers):
            raise BackupError(f'{context}: invalid mysql --batch row {number}: '
                              f'expected {len(headers)} columns, received {len(fields)}. '
                              'Export stopped; no SQL text was discarded.')
        result.append({header: decode_batch_field(value)
                       for header, value in zip(headers, fields)})
    return result


def prompt(label, default=None, required=False):
    while True:
        value = input(label + (f' [{default}]' if default is not None else '') + ': ').strip()
        value = value or (str(default) if default is not None else '')
        if value or not required:
            return value
        print('Please enter a value.')


def yes(label):
    return prompt(label + ' (y/N)').lower() in ('y', 'yes')


def ident(value):
    return '`' + value.replace('`', '``') + '`'


def literal(value):
    return 'CONVERT(0x' + value.encode('utf-8').hex() + ' USING utf8mb4)' if value else "''"


def safe_filename(value):
    cleaned = re.sub(r'[^A-Za-z0-9_.-]', '_', value).strip('.')[:100] or 'backup'
    if cleaned != value:
        cleaned += '-' + hashlib.sha256(value.encode()).hexdigest()[:10]
    return cleaned


def command(args, **kwargs):
    try:
        result = subprocess.run(args, stderr=subprocess.PIPE, **kwargs)
    except OSError as error:
        raise BackupError(str(error)) from error
    if result.returncode:
        message = result.stderr.decode('utf-8', errors='replace').strip()
        raise BackupError(message or f'{args[0]} failed (exit {result.returncode})')
    if result.stderr:
        print(result.stderr.decode('utf-8', errors='replace').strip(), file=sys.stderr)
    return result


def transform_sql(sql):
    namespace = {}
    exec(compile(RESOURCES['transformer.py'], 'embedded-transformer.py', 'exec'), namespace)
    return namespace['transform'](sql)


def generator_sql(names=GENERATORS):
    # The client's delimiter directives are intentionally retained in the bundle.
    parts = ['CREATE DATABASE IF NOT EXISTS `tools` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;',
             'USE `tools`;', 'SET @FLEX_OLD_SQL_MODE=@@SESSION.sql_mode;',
             "SET SESSION sql_mode='NO_ENGINE_SUBSTITUTION';"]
    for name in names:
        sql = RESOURCES[name + '.sql']
        # Only the CREATE PROCEDURE prefix: preserve DEFINER text emitted into backups.
        sql = re.sub(r'CREATE\s+DEFINER=`Sup_User_SPESA`@`%`\s+PROCEDURE',
                     'CREATE DEFINER=CURRENT_USER PROCEDURE', sql, count=1, flags=re.I)
        # Helpers must propagate errors; a diagnostic SELECT falsely looks like an SQL backup.
        sql = re.sub(r'(GET DIAGNOSTICS CONDITION 1[^;]*;\s*)SELECT[^;]*;',
                     r'\1RESIGNAL;', sql, count=1, flags=re.I)
        sql = re.sub(r'\butf8_general_ci\b', 'utf8mb4_general_ci', sql, flags=re.I)
        sql = re.sub(r'\butf8\b', 'utf8mb4', sql, flags=re.I)
        # VARCHAR(21845) fits three-byte utf8, but exceeds 65535 bytes in utf8mb4.
        sql = re.sub(r'\bSchemaNames VARCHAR\(21845\)', 'SchemaNames TEXT', sql, flags=re.I)
        parts.append(sql)
    parts.append('SET SESSION sql_mode=@FLEX_OLD_SQL_MODE;')
    return '\n\n'.join(parts) + '\n'


class Client:
    def __init__(self, host, port, user, password, output):
        self.env = dict(os.environ, MYSQL_PWD=password, MYSQL_TEST_LOGIN_FILE='/dev/null')
        self.base = ['--no-defaults', '--default-character-set=utf8mb4', '--protocol=TCP',
                     '--host=' + host, '--port=' + port, '--user=' + user]
        self.mysql = ['mysql', *self.base, '--batch',
                      '--init-command=SET NAMES utf8mb4 COLLATE utf8mb4_general_ci']
        self.output = Path(output).expanduser().resolve()
        self.host = host

    def query(self, sql, rows=False, context=None, required_columns=()):
        context = context or ('MySQL query: ' + sql.split('\n', 1)[0][:160])
        result = command([*self.mysql, '--execute', sql],
                         env=self.env, stdout=subprocess.PIPE)
        try:
            text = result.stdout.decode('utf-8')
        except UnicodeDecodeError as error:
            raise BackupError(f'{context}: mysql returned invalid UTF-8 at byte {error.start}; export stopped.') from error
        if not rows:
            return text
        return parse_batch_rows(text, context, required_columns)

    def install(self, names):
        if not names:
            return
        print('Installing in tools: ' + ', '.join(names))
        command(self.mysql, input=generator_sql(names).encode('utf-8'), env=self.env,
                stdout=subprocess.PIPE)
        present = self.present()
        missing = set(names) - present
        if missing:
            raise BackupError('Installation incomplete: ' + ', '.join(sorted(missing)))
        print('Generator installation completed.')

    def present(self):
        rows = self.query("SELECT ROUTINE_NAME FROM information_schema.ROUTINES "
                          "WHERE ROUTINE_SCHEMA='tools' AND ROUTINE_TYPE='PROCEDURE'", rows=True,
                          required_columns=('ROUTINE_NAME',))
        return {row['ROUTINE_NAME'] for row in rows}

    def ensure(self, name):
        if name in self.present():
            return True
        print(f'Missing generator: tools.{name}')
        if not yes('Install this bundled generator now'):
            return False
        self.install([name])
        return True

    def directory(self, category):
        self.output.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_')
        folder = Path(tempfile.mkdtemp(prefix=safe_filename(self.host) + '_' + stamp + category + '_',
                                       dir=self.output))
        return folder

    def definitions(self, generator, arguments, category):
        if generator == 'gen_event_script':
            schema, event = arguments
            conditions = ["EVENT_TYPE<>'RECURRING'"]
            if schema:
                conditions.append('EVENT_SCHEMA=' + literal(schema))
            if event:
                conditions.append('EVENT_NAME=' + literal(event))
            unsupported = self.query('SELECT EVENT_SCHEMA,EVENT_NAME FROM information_schema.EVENTS WHERE '
                                     + ' AND '.join(conditions), rows=True,
                                     required_columns=('EVENT_SCHEMA', 'EVENT_NAME'))
            if unsupported:
                raise BackupError('The legacy event generator cannot export one-time events. '
                                  'Export stopped to avoid silently omitting: ' + ', '.join(
                                      r['EVENT_SCHEMA'] + '.' + r['EVENT_NAME'] for r in unsupported))
        if not self.ensure(generator):
            return
        raw = self.query('CALL tools.' + generator + '(' + ','.join(
            str(a) if isinstance(a, int) else literal(a) for a in arguments) + ');')
        header = raw.split('\n', 1)[0] if raw else ''
        if re.search(r'\b(errNom|errText|res)\b', header, flags=re.I):
            raise BackupError('The installed generator returned diagnostics, not SQL:\n' + raw[:1200])
        if not raw:
            print('No matching objects returned. No backup file was created.')
            return
        if '\t' in header:
            raise BackupError(f'Exporting {category}: expected one SQL result column from {generator}.')
        # Retain sed header removal. Decode complete batch fields afterwards:
        # expanding only \\n leaves \\t active as mysql's notee command and can
        # corrupt literal SQL escape sequences. Do not decode the result twice.
        data = command(['sed', '1d'], input=raw.encode('utf-8'), stdout=subprocess.PIPE).stdout.decode('utf-8')
        lines = data.split('\n')
        if lines[-1] == '':
            lines.pop()
        statements = []
        for number, line in enumerate(lines, start=1):
            if '\t' in line:
                raise BackupError(f'Exporting {category}: unexpected result columns in row {number}.')
            if line == 'NULL':
                continue
            statements.append(decode_batch_field(line))
        data = '\n'.join(statements).encode('utf-8')
        if not data.strip():
            print('No matching objects returned. No backup file was created.')
            return
        if not data.endswith(b'\n'):
            data += b'\n'
        folder = self.directory(category)
        path = folder / (category + '.sql')
        try:
            path.write_bytes(data)
        except OSError:
            path.unlink(missing_ok=True)
            raise
        print(f'Saved: {path}')

    def routines(self, schema, routine, migrate):
        patterns = json.loads(os.environ.get('EXCLUDE_SP_PATTERNS_JSON', json.dumps(DEFAULT_PATTERNS)))
        schemas = json.loads(os.environ.get('EXCLUDED_SCHEMAS_JSON', '[]'))
        if not isinstance(patterns, list) or not isinstance(schemas, list) or any(
                not isinstance(v, str) for v in patterns + schemas):
            raise BackupError('Routine exclusion settings must be JSON arrays of strings.')
        digits = int(os.environ.get('MAX_DIGITS_IN_NAME', '5'))
        if digits < 0:
            raise BackupError('MAX_DIGITS_IN_NAME must be nonnegative.')
        conditions = ['ROUTINE_SCHEMA NOT IN (' + ','.join(literal(s) for s in SYSTEM_SCHEMAS) + ')']
        if schema:
            conditions.append('ROUTINE_SCHEMA=' + literal(schema))
        if routine:
            conditions.append('ROUTINE_NAME=' + literal(routine))
        conditions += ['ROUTINE_NAME NOT LIKE ' + literal(p) for p in patterns]
        conditions += ['ROUTINE_SCHEMA<>' + literal(s) for s in schemas]
        if digits:
            conditions.append("ROUTINE_NAME NOT REGEXP '[0-9]" + '.*[0-9]' * (digits - 1) + "'")
        rows = self.query('SELECT ROUTINE_SCHEMA,ROUTINE_NAME,ROUTINE_TYPE FROM information_schema.ROUTINES WHERE '
                          + ' AND '.join(conditions) + ' ORDER BY ROUTINE_SCHEMA,ROUTINE_NAME',
                          rows=True, context='Reading the stored procedure/function list',
                          required_columns=('ROUTINE_SCHEMA', 'ROUTINE_NAME', 'ROUTINE_TYPE'))
        if not rows:
            print('No routines matched (including the configured exclusions).')
            return
        folder = self.directory('routines')
        path = folder / 'routines.sql'
        temp = folder / 'routines.sql.partial'
        try:
            with temp.open('w', encoding='utf-8', newline='') as stream:
                for row in rows:
                    kind, db, name = row['ROUTINE_TYPE'], row['ROUTINE_SCHEMA'], row['ROUTINE_NAME']
                    if kind not in ('PROCEDURE', 'FUNCTION'):
                        raise BackupError('Unexpected routine type: ' + str(kind))
                    result = self.query(f'SHOW CREATE {kind} {ident(db)}.{ident(name)}', rows=True,
                                        context=f'Reading {kind} {ident(db)}.{ident(name)}',
                                        required_columns=('Create ' + kind.title(),))
                    create = result[0].get('Create ' + kind.title()) if result else None
                    if not create or create == 'NULL':
                        raise BackupError('SHOW CREATE returned no body for ' + db + '.' + name)
                    # Unique delimiter avoids collisions with tokens inside the original body.
                    delimiter = ';;'
                    while delimiter in create:
                        delimiter += ';'
                    sql = (f'USE {ident(db)};\nDROP {kind} IF EXISTS {ident(name)};\n'
                           f'DELIMITER {delimiter}\n{create}\n{delimiter}\nDELIMITER ;\n\n')
                    stream.write(transform_sql(sql) if migrate else sql)
            temp.replace(path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        print(f'Saved {len(rows)} routines: {path}')

    def data(self, schema, table, engine):
        if not shutil.which('mysqldump'):
            raise BackupError('mysqldump is required for data backups.')
        # Preserve gen_data_script dump flags, but select actual tables so EngineName
        # cannot silently produce a whole-schema backup. Never execute generated shell text.
        conditions = ["TABLE_SCHEMA NOT IN ('information_schema','performance_schema','mysql','ndbinfo','sys','ndbmemcache','_development','_test')",
                      "TABLE_TYPE='BASE TABLE'"]
        for column, value in [('TABLE_SCHEMA', schema), ('TABLE_NAME', table), ('ENGINE', engine)]:
            if value:
                conditions.append(column + '=' + literal(value))
        rows = self.query('SELECT TABLE_SCHEMA,TABLE_NAME,ENGINE FROM information_schema.TABLES WHERE '
                          + ' AND '.join(conditions) + ' ORDER BY TABLE_SCHEMA,TABLE_NAME', rows=True,
                          required_columns=('TABLE_SCHEMA', 'TABLE_NAME', 'ENGINE'))
        if not rows:
            print('No matching tables. No data backup was created.')
            return
        groups = collections.defaultdict(list)
        for row in rows:
            groups[row['TABLE_SCHEMA']].append((row['TABLE_NAME'], row['ENGINE']))
        help_text = command(['mysqldump', '--no-defaults', '--help'], env=self.env,
                            stdout=subprocess.PIPE).stdout.decode('utf-8', errors='replace')
        flags = ['--no-create-db', '--no-create-info', '--skip-triggers', '--extended-insert', '--no-tablespaces']
        if 'column-statistics' in help_text:
            flags.append('--column-statistics=0')
        folder = self.directory('data')
        completed = []
        try:
            for db, tables in groups.items():
                path = folder / (safe_filename(db) + '_data.sql')
                temp = path.with_suffix('.sql.partial')
                with temp.open('wb') as stream:
                    # Without --databases: following arguments are tables, not more databases.
                    stream.write(('USE ' + ident(db) + ';\n').encode('utf-8'))
                    command(['mysqldump', *self.base, *flags, '--', db,
                             *[name for name, _ in tables]], env=self.env, stdout=stream)
                temp.replace(path)
                completed.append(path)
        except BaseException:
            for partial in folder.glob('*.partial'):
                partial.unlink()
            print(f'Data backup incomplete. Completed schema files: {len(completed)}. Folder: {folder}', file=sys.stderr)
            raise
        print(f'Saved {len(completed)} data files: {folder}')
        print('Data-only export; restore schema and table structures first. '
              'Separate dumps do not provide a coordinated snapshot across schemas or NDB tables.')


def scope(label):
    print(f'\n{label}\n1. All databases\n2. One database\n3. One object\n0. Back')
    choice = prompt('Choice')
    if choice == '0':
        return None
    if choice not in ('1', '2', '3'):
        raise BackupError('Invalid choice.')
    db = prompt('Database name', required=True) if choice != '1' else ''
    name = prompt('Object name', required=True) if choice == '3' else ''
    return db, name


def table_options(client, data=False):
    selected = scope('Table data' if data else 'Table structures')
    if selected is None:
        return
    db, table = selected
    engine = prompt('Engine filter (blank = all)')
    # Table generator internally interpolates EngineName into dynamic SQL.
    if engine and not re.fullmatch(r'[A-Za-z0-9_]+', engine):
        raise BackupError('Engine must contain only letters, numbers and underscores.')
    if data:
        client.data(db, table, engine)
        return
    charset = prompt('Target character set (blank = preserve)')
    collation = prompt('Target collation (blank = preserve)')
    if charset and not re.fullmatch(r'[A-Za-z0-9_]+', charset):
        raise BackupError('Invalid character set name.')
    if collation and not re.fullmatch(r'[A-Za-z0-9_]+', collation):
        raise BackupError('Invalid collation name.')
    if bool(charset) != bool(collation):
        raise BackupError('Enter both target charset and collation, or leave both blank.')
    if charset:
        rows = client.query('SELECT COLLATION_NAME FROM information_schema.COLLATIONS WHERE COLLATION_NAME='
                            + literal(collation) + ' AND CHARACTER_SET_NAME=' + literal(charset), rows=True,
                            required_columns=('COLLATION_NAME',))
        if not rows:
            raise BackupError('The selected charset/collation pair is not available on the source server.')
    # The legacy table generator embeds schema names into dynamic quoted SQL.
    # Validate all selected schema names before invoking it.
    schema_rows = client.query('SELECT SCHEMA_NAME FROM information_schema.SCHEMATA WHERE '
                               + ('SCHEMA_NAME=' + literal(db) if db else 'SCHEMA_NAME NOT IN (' + ','.join(literal(s) for s in SYSTEM_SCHEMAS) + ')'), rows=True,
                               required_columns=('SCHEMA_NAME',))
    if any(not re.fullmatch(r'[A-Za-z0-9_$-]+', r['SCHEMA_NAME']) for r in schema_rows):
        raise BackupError('This legacy table generator requires simple database names (letters, numbers, _, $, -).')
    # Legacy GROUP_CONCAT iteration uses commas as separators; reject ambiguous names.
    name_rows = client.query('SELECT TABLE_NAME FROM information_schema.TABLES WHERE '
                             + ('TABLE_SCHEMA=' + literal(db) if db else 'TABLE_SCHEMA NOT IN (' + ','.join(literal(s) for s in SYSTEM_SCHEMAS) + ')')
                             + (' AND TABLE_NAME=' + literal(table) if table else '')
                             + " AND TABLE_TYPE='BASE TABLE'" + (' AND ENGINE=' + literal(engine) if engine else ''), rows=True,
                             required_columns=('TABLE_NAME',))
    if not name_rows:
        print('No matching tables.')
        return
    if any(',' in r['TABLE_NAME'] for r in name_rows):
        raise BackupError('The legacy table generator cannot safely process table names containing commas.')
    client.definitions('gen_table_script', [1, db, table, engine, charset, collation], 'tables')


def interactive(args):
    for executable in ('mysql', 'sed'):
        if not shutil.which(executable):
            raise BackupError(executable + ' is required.')
    if 'GNU sed' not in command(['sed', '--version'], stdout=subprocess.PIPE).stdout.decode(errors='replace'):
        raise BackupError('GNU sed is required by the original export pipelines.')
    print('flexmysqlbackup ' + VERSION + ' — interactive SQL exports')
    host = args.host or prompt('MySQL host', os.environ.get('MYSQL_HOST', 'localhost'))
    port = args.port or prompt('MySQL port', os.environ.get('MYSQL_PORT', '3306'))
    user = args.user or prompt('MySQL user', os.environ.get('MYSQL_USER', 'devops'))
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise BackupError('Invalid TCP port.')
    password = getpass.getpass('MySQL password: ')
    output = args.output or prompt('Output directory', './backups')
    client = Client(host, port, user, password, output)
    info = client.query('SELECT VERSION() AS version, CURRENT_USER() AS account', rows=True,
                        required_columns=('version', 'account'))
    print('Connected: ' + str(info[0].get('account')) + ' — MySQL ' + str(info[0].get('version')))
    while True:
        print('\n1. Schemas (databases)\n2. Table structures\n3. Table data\n4. Views\n'
              '5. Stored procedures and functions\n6. Triggers\n7. Events\n'
              '8. Install/update bundled generators\n0. Exit')
        choice = prompt('Choice')
        try:
            if choice == '0':
                break
            if choice == '1':
                print('\n1. All schemas selected by the generator\n2. One schema\n0. Back')
                sub = prompt('Choice')
                if sub == '0':
                    continue
                if sub not in ('1', '2'):
                    raise BackupError('Invalid choice.')
                db = prompt('Database name', required=True) if sub == '2' else ''
                client.definitions('gen_schemes_script', [db], 'schemas')
            elif choice in ('2', '3'):
                table_options(client, data=choice == '3')
            elif choice in ('4', '5', '6', '7'):
                selected = scope({'4':'Views', '5':'Routines', '6':'Triggers', '7':'Events'}[choice])
                if selected is None:
                    continue
                if choice == '5':
                    print('\n1. Apply process_sql_opt migration transformations\n2. Export original definitions')
                    mode = prompt('Choice', '1')
                    if mode not in ('1', '2'):
                        raise BackupError('Invalid choice.')
                    client.routines(*selected, migrate=mode == '1')
                else:
                    if choice == '6' and any("'" in s or '\\' in s for s in selected):
                        raise BackupError('The legacy trigger generator cannot safely filter names containing quotes or backslashes.')
                    generator, category = {'4':('gen_view_script','views'), '6':('gen_triggers_script','triggers'),
                                           '7':('gen_event_script','events')}[choice]
                    client.definitions(generator, list(selected), category)
            elif choice == '8':
                present = client.present()
                missing = [name for name in GENERATORS if name not in present]
                print('Missing: ' + (', '.join(missing) or 'none'))
                print('1. Install missing generators\n2. Replace all six generators\n0. Back')
                action = prompt('Choice')
                if action == '1':
                    client.install(missing)
                elif action == '2':
                    if yes('Replace only these six tools procedures with the bundled versions'):
                        client.install(GENERATORS)
                elif action != '0':
                    raise BackupError('Invalid choice.')
            else:
                print('Invalid choice.')
        except (BackupError, OSError, ValueError) as error:
            print('ERROR: ' + str(error), file=sys.stderr)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(prog='flexmysqlbackup.sh', description='Single-file flexmysqlbackup installer and interactive exporter.')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--host')
    parser.add_argument('--port')
    parser.add_argument('--user')
    parser.add_argument('--output', help='Backup output directory')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--transform', nargs='+', metavar='SQL_FILE', help='Offline: input.sql [output.sql]')
    modes.add_argument('--extract-install-sql', metavar='PATH', help='Write combined installer without connecting')
    args = parser.parse_args()
    if args.transform:
        if len(args.transform) not in (1, 2):
            parser.error('--transform requires input.sql [output.sql]')
        source = Path(args.transform[0])
        path = Path(args.transform[-1])
        result = transform_sql(source.read_bytes().decode('utf-8'))
        fd, temp = tempfile.mkstemp(prefix='.flex-transform-', dir=path.parent)
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
                stream.write(result)
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return
    if args.extract_install_sql:
        with open(args.extract_install_sql, 'x', encoding='utf-8', newline='') as stream:
            stream.write(generator_sql())
        print('Saved installer: ' + args.extract_install_sql)
        return
    interactive(args)


if __name__ == '__main__':
    try:
        main()
    except (BackupError, OSError, ValueError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.', file=sys.stderr)
        sys.exit(130)
