#!/bin/bash
set -e

# Export mode is interactive; --transform skips password and menu prompts.
if [[ "${1:-}" != "--transform" ]]; then
    # Define MySQL credentials
    MYSQL_USER="devops"
    MYSQL_HOST="SERVER_IP"
    MYSQL_PORT="3306"

    # Prompt for the password without showing it
    echo -n "Enter MySQL password: "
    IFS= read -r -s MYSQL_PASS
    export MYSQL_PWD="$MYSQL_PASS"
    # --no-defaults skips option files but still reads login paths on MySQL 8.0.
    # Use only the password entered above, including in generated commands.
    export MYSQL_TEST_LOGIN_FILE=/dev/null
    echo

    # Define output files
    PROC_FILE="proc.sql"
    TEMP_CMD_FILE="commands.sh"

    # Display menu options
    echo "Choose an option:"
    echo "1. Create all stored procedures and functions from all databases"
    echo "2. Create only one specific stored procedure or function"
    echo "3. Create all stored procedures and functions from a specific database"
    read -r -p "Enter your choice (1/2/3): " choice
fi

# Request UTF-8 explicitly, including on legacy servers whose handshake may
# fall back to latin1 when an 8.x client requests an unknown collation.
MYSQL_INIT_COMMAND="SET NAMES utf8mb4 COLLATE utf8mb4_general_ci"
export MYSQL_INIT_COMMAND

# Requires Python 3 (standard library only).
# Offline: bash process_sql_opt.sh --transform input.sql [output.sql]
# SQL LIKE patterns: % matches any string; _ matches one character.
EXCLUDE_SP_PATTERNS=(
    '%copy' '%copy1' '%copy2' '%copy3'
    'alter_table' '%transfer_casino_balance_shard%'
)
EXCLUDED_SCHEMAS=()      # Example: ('test' 'backup')
MAX_DIGITS_IN_NAME=5     # Exclude routines with 5+ digits total, including dates; 0 disables.
# Migration identifiers: extend as needed; this is not a full SQL parser.
QUOTE_IDENTIFIERS="over groups rank dense_rank row_number cume_dist percent_rank ntile lag lead first_value last_value nth_value recursive window lateral"
export QUOTE_IDENTIFIERS
# Upgrade utf8/utf8mb3 routine and CREATE TABLE definitions to utf8mb4.
CONVERT_UTF8_TO_UTF8MB4=1
export CONVERT_UTF8_TO_UTF8MB4
# Remove only legacy DESC modifiers from GROUP BY; add no sorting.
REMOVE_GROUP_BY_DESC=1
export REMOVE_GROUP_BY_DESC

transform_sql() {
python3 - "$@" <<'PY_SQL'
import os
import re
import sys
import tempfile
from pathlib import Path

BT = chr(96)
PATTERN = re.compile(
    r"(?P<skip>\s+|--(?=\s|$)[^\r\n]*|\#[^\r\n]*|/\*.*?\*/)"
    r"|(?P<string>'(?:\\.|''|[^'\\])*'|\"(?:\\.|\"\"|[^\"\\])*\")"
    r"|(?P<session>@@?(?:" + BT + r"(?:" + BT*2 + r"|[^" + BT + r"])*" + BT + r"|[\w$]+))"
    r"|(?P<identifier>" + BT + r"(?:" + BT*2 + r"|[^" + BT + r"])*" + BT + r")"
    r"|(?P<word>[A-Za-z_$][\w$]*)|(?P<number>\d+)|(?P<symbol>.)",
    re.DOTALL,
)

def lex(sql):
    result = []
    for m in PATTERN.finditer(sql):
        if m.lastgroup == 'skip':
            continue
        if m.lastgroup == 'symbol' and m.group() in ("'", '"', BT):
            raise ValueError('Unterminated SQL literal or identifier')
        result.append((m.lastgroup, m.group(), m.start(), m.end()))
    return result

def name(token):
    return token[1].strip(BT).replace(BT*2, BT).lower()

def edit(sql, changes):
    boundary = len(sql) + 1
    for a, b, value in sorted(changes, reverse=True):
        if b > boundary:
            raise ValueError('Overlapping SQL edits')
        sql = sql[:a] + value + sql[b:]
        boundary = a
    return sql

def blocks(ts):
    stack, pairs = [], {}
    for i, t in enumerate(ts):
        if t[0] != 'word':
            continue
        w = name(t)
        prev = name(ts[i-1]) if i else ''
        after = name(ts[i+1]) if i+1 < len(ts) else ''
        if w in ('begin', 'case') and prev != 'end':
            stack.append((w, i))
        elif w == 'end' and after not in ('if', 'loop', 'while', 'repeat'):
            if stack:
                kind, start = stack.pop()
                if kind == 'begin':
                    pairs[start] = i
    return pairs

def handlers(ts, pairs):
    result = []
    for i in range(len(ts)-4):
        if (name(ts[i]) != 'declare' or name(ts[i+1]) not in ('exit','continue','undo')
                or name(ts[i+2]) != 'handler' or name(ts[i+3]) != 'for'):
            continue
        j = i+4
        while j < len(ts):
            if name(ts[j]) == 'sqlstate':
                j += 1
                if j < len(ts) and name(ts[j]) == 'value':
                    j += 1
                j += 1
            elif name(ts[j]) == 'not':
                j += 2
            else:
                j += 1
            if j < len(ts) and ts[j][1] == ',':
                j += 1
            else:
                break
        if j >= len(ts):
            raise ValueError('Incomplete handler')
        if name(ts[j]) == 'begin':
            if j not in pairs:
                raise ValueError('Unbalanced handler BEGIN/END')
            end = pairs[j]
        elif name(ts[j]) in ('if','case','while','loop','repeat'):
            raise ValueError('Please wrap compound handler statements in BEGIN/END')
        else:
            end = next((k for k in range(j,len(ts)) if ts[k][1] == ';'), len(ts)-1)
        result.append((j,end))
    return result

def column_positions(ts):
    # INSERT lists and UPDATE assignment targets are column names, not locals.
    positions = set()
    for i,t in enumerate(ts):
        if t[0] != 'word' or name(t) != 'insert':
            continue
        j = i+1
        while j < len(ts) and name(ts[j]) in ('ignore','into','low_priority','delayed','high_priority'):
            j += 1
        if j >= len(ts):
            continue
        j += 1
        while j+1 < len(ts) and ts[j][1] == '.':
            j += 2
        if j < len(ts) and ts[j][1] == '(':
            end = next((k for k in range(j+1,len(ts)) if ts[k][1] == ')'), j)
            positions.update(range(j+1,end))
    for i,t in enumerate(ts):
        if t[0] != 'word' or name(t) != 'update':
            continue
        j = i+1
        if i == 0 or name(ts[i-1]) != 'key':
            while j < len(ts) and name(ts[j]) != 'set' and ts[j][1] != ';':
                j += 1
            j += 1
        depth, lhs = 0, True
        while j < len(ts) and ts[j][1] != ';':
            if depth == 0 and name(ts[j]) in ('where','order','limit'):
                break
            if depth == 0 and lhs:
                positions.add(j)
                lhs = False
            if ts[j][1] == '(':
                depth += 1
            elif ts[j][1] == ')':
                depth -= 1
            elif depth == 0 and ts[j][1] == ',':
                lhs = True
            j += 1
    return positions

def migrate_errors(sql):
    ts = lex(sql)
    pairs = blocks(ts)
    hs = handlers(ts,pairs)
    inside = lambda k: any(a <= k <= b for a,b in hs)
    target = {'errnom':'@errNom','errtext':'@errText'}
    types = set(('tinyint smallint mediumint int integer bigint decimal numeric float double real '
                 'bit bool boolean char varchar binary varbinary tinytext text mediumtext longtext '
                 'tinyblob blob mediumblob longblob date time datetime timestamp year json enum set').split())
    declarations, names = [], set()
    for i,t in enumerate(ts):
        if t[0] != 'word' or name(t) != 'declare':
            continue
        j, ns = i+1, []
        while j < len(ts) and ts[j][0] in ('word','identifier'):
            ns.append(j)
            j += 1
            if j < len(ts) and ts[j][1] == ',':
                j += 1
            else:
                break
        if not ns or j >= len(ts) or name(ts[j]) not in types:
            continue
        end = next((k for k in range(j,len(ts)) if ts[k][1] == ';'),None)
        if end is None:
            raise ValueError('Unterminated DECLARE')
        scope = max(((a,b) for a,b in pairs.items() if a<i<b),
                    default=(-1,len(ts)),key=lambda x:x[0])
        declarations.append((i,end,ns,scope))
        names.update(ns)

    def binding(k,n):
        found = [(d[3][0],p) for d in declarations for p in d[2]
                 if name(ts[p]) == n and d[3][0] < k < d[3][1]]
        return max(found,default=(-2,None))[1]

    columns = column_positions(ts)
    def reference(k):
        return (k not in columns and k not in names
                and (k == 0 or name(ts[k-1]) not in ('.','as'))
                and (k+1 == len(ts) or ts[k+1][1] not in ('.','(')))

    migrated = set()
    for k,t in enumerate(ts):
        n = name(t).lstrip('@')
        if n in target and inside(k) and reference(k):
            p = binding(k,n)
            if p is not None:
                migrated.add(p)
    changes, deleted = [], []
    for a,b,ns,_ in declarations:
        if not any(p in migrated for p in ns):
            continue
        if all(p in migrated for p in ns):
            span = (ts[a][2],ts[b][3])
            changes.append((*span,''))
            deleted.append(span)
        else:
            k = 0
            while k < len(ns):
                if ns[k] not in migrated:
                    k += 1
                    continue
                first = k
                while k+1 < len(ns) and ns[k+1] in migrated:
                    k += 1
                span = ((ts[ns[first]][2],ts[ns[k]+1][3]) if k+1 < len(ns)
                        else (ts[ns[first]-1][2],ts[ns[k]][3]))
                changes.append((*span,''))
                deleted.append(span)
                k += 1
    for k,t in enumerate(ts):
        n = name(t)
        if (t[0] not in ('word','identifier') or n not in target or not reference(k)
                or any(a <= t[2] < b for a,b in deleted)):
            continue
        p = binding(k,n)
        # Follow removed bindings outside the handler too, avoiding dangling uses.
        if p in migrated or (p is None and inside(k)):
            changes.append((t[2],t[3],target[n]))
    return edit(sql,changes)

def convert_utf8_definitions(sql):
    if os.environ.get('CONVERT_UTF8_TO_UTF8MB4', '1') != '1':
        return sql
    ts = lex(sql)
    string_types = {'char', 'character', 'varchar', 'nchar', 'nvarchar', 'national',
                    'tinytext', 'text', 'mediumtext', 'longtext', 'enum', 'set'}
    ranges = []

    def type_range(start, end):
        if start >= end or ts[start][0] != 'word' or name(ts[start]) not in string_types:
            return
        # DEFAULT expressions can have their own meaningful COLLATE clauses.
        end = next((k for k in range(start, end)
                    if ts[k][0] == 'word' and name(ts[k]) == 'default'), end)
        ranges.append((start, end))

    def top_level_ranges(start, end, stop_words=()):
        # Column DEFAULT/generated expressions and partition expressions may
        # contain runtime COLLATE clauses. Only collect definition attributes.
        depth, run = 0, start
        for k in range(start, end):
            if ts[k][1] == '(':
                if depth == 0 and run < k:
                    ranges.append((run, k))
                depth += 1
            elif ts[k][1] == ')':
                depth -= 1
                if depth == 0:
                    run = k + 1
            elif depth == 0 and ts[k][0] == 'word' and name(ts[k]) in stop_words:
                if run < k:
                    ranges.append((run, k))
                return
        if depth == 0 and run < end:
            ranges.append((run, end))

    # Local variables, including a shared type for DECLARE a,b,c VARCHAR(...).
    for i, t in enumerate(ts):
        if t[0] != 'word' or name(t) != 'declare':
            continue
        j = i + 1
        while j < len(ts) and ts[j][0] in ('word', 'identifier'):
            j += 1
            if j < len(ts) and ts[j][1] == ',':
                j += 1
            else:
                break
        end = next((k for k in range(j, len(ts)) if ts[k][1] == ';'), len(ts))
        type_range(j, end)

    # Routine signatures plus CREATE [TEMPORARY] TABLE definitions in bodies.
    for i, t in enumerate(ts):
        if t[0] != 'word' or name(t) != 'create':
            continue
        kind = next((k for k in range(i + 1, len(ts))
                     if ts[k][0] == 'word' and name(ts[k]) in
                     ('procedure', 'function', 'table', 'view', 'trigger', 'event')
                     or ts[k][1] == ';'), None)
        if kind is None or name(ts[kind]) not in ('procedure', 'function', 'table'):
            continue
        if name(ts[kind]) == 'table':
            j = kind + 1
            if ([name(t) for t in ts[j:j + 3]] == ['if', 'not', 'exists']):
                j += 3
            if j >= len(ts) or ts[j][0] not in ('word', 'identifier'):
                continue
            j += 1  # table name, optionally qualified with a schema
            if j < len(ts) and ts[j][1] == '.':
                j += 2
            end = next((k for k in range(j, len(ts)) if ts[k][1] == ';'), len(ts))
            if j < end and ts[j][1] == '(':
                depth, start, closing = 1, j + 1, None
                for k in range(j + 1, end):
                    if ts[k][1] == '(':
                        depth += 1
                    elif ts[k][1] == ')':
                        depth -= 1
                    if depth == 0 or (depth == 1 and ts[k][1] == ','):
                        # Skip the column name; constraints/indexes have no
                        # string data type in this position.
                        column_type = start + 1
                        if (column_type < k and ts[column_type][0] == 'word'
                                and name(ts[column_type]) in string_types):
                            top_level_ranges(column_type, k,
                                             ('as', 'generated', 'check', 'references'))
                        start = k + 1
                    if depth == 0:
                        closing = k
                        break
                if closing is None:
                    raise ValueError('Unbalanced CREATE TABLE column definitions')
                j = closing + 1
            # DEFAULT CHARSET[=]utf8, [DEFAULT] CHARACTER SET [=] utf8,
            # and COLLATE[=]utf8_*; SELECT/LIKE contents remain expressions.
            top_level_ranges(j, end, ('as', 'select', 'like', 'partition'))
            continue
        j = kind + 2  # routine name
        if j < len(ts) and ts[j][1] == '.':
            j += 2
        if j >= len(ts) or ts[j][1] != '(':
            continue
        depth, start, closing = 1, j + 1, None
        for k in range(j + 1, len(ts)):
            if ts[k][1] == '(':
                depth += 1
            elif ts[k][1] == ')':
                depth -= 1
            if depth == 0 or (depth == 1 and ts[k][1] == ','):
                parameter = start
                if parameter < k and name(ts[parameter]) in ('in', 'out', 'inout'):
                    parameter += 1
                type_range(parameter + 1, k)  # skip the parameter name
                start = k + 1
            if depth == 0:
                closing = k
                break
        if (closing is not None and name(ts[kind]) == 'function'
                and closing + 1 < len(ts) and name(ts[closing + 1]) == 'returns'):
            start = closing + 2
            stops = {'language', 'deterministic', 'not', 'contains', 'no', 'reads',
                     'modifies', 'sql', 'comment', 'begin', 'return'}
            end = next((k for k in range(start, len(ts))
                        if ts[k][1] == ';' or
                        (ts[k][0] == 'word' and name(ts[k]) in stops)), len(ts))
            type_range(start, end)

    def value(t):
        return t[1][1:-1].lower() if t[0] == 'string' else name(t)

    # Legacy collation families with a corresponding utf8mb4 collation in
    # MySQL 8.4. Do not manufacture a target for an unknown/custom collation.
    collation_suffixes = {
        'bin', 'general_ci', 'unicode_ci', 'unicode_520_ci', 'icelandic_ci',
        'latvian_ci', 'romanian_ci', 'slovenian_ci', 'polish_ci', 'estonian_ci',
        'spanish_ci', 'swedish_ci', 'turkish_ci', 'czech_ci', 'danish_ci',
        'lithuanian_ci', 'slovak_ci', 'spanish2_ci', 'roman_ci', 'persian_ci',
        'esperanto_ci', 'hungarian_ci', 'sinhala_ci', 'german2_ci',
        'croatian_ci', 'vietnamese_ci',
    }

    changes = []
    for start, end in ranges:
        i = start
        while i < end:
            j = i
            if ts[i][0] != 'word':
                i += 1
                continue
            word = name(ts[i])
            if word == 'character' and i + 1 < end and name(ts[i + 1]) == 'set':
                j = i + 2
            elif word in ('charset', 'collate'):
                j = i + 1
            else:
                i += 1
                continue
            if j < end and ts[j][1] == '=':
                j += 1
            pattern = r'utf8(?:mb3)?_([a-z0-9_]+)' if word == 'collate' else r'utf8(?:mb3)?'
            if (j >= end or ts[j][0] not in ('word', 'identifier', 'string')
                    or not re.fullmatch(pattern, value(ts[j]))):
                i += 1
                continue
            replacement = 'utf8mb4'
            if word == 'collate':
                suffix = re.fullmatch(pattern, value(ts[j])).group(1)
                if suffix not in collation_suffixes:
                    raise ValueError('No verified utf8mb4 equivalent for collation '
                                     + value(ts[j]) + '; choose its target explicitly')
                replacement += '_' + suffix
            # Replace only the value token, retaining quotes and every comment.
            if ts[j][0] in ('identifier', 'string'):
                replacement = ts[j][1][0] + replacement + ts[j][1][-1]
            changes.append((ts[j][2], ts[j][3], replacement))
            i = j + 1
    return edit(sql, changes)

def remove_group_by_desc(sql):
    if os.environ.get('REMOVE_GROUP_BY_DESC', '1') != '1':
        return sql
    ts = lex(sql)
    depths, depth = [], 0
    for t in ts:
        depths.append(depth)
        if t[1] == '(':
            depth += 1
        elif t[1] == ')':
            depth -= 1

    def keyword(k, words):
        return (k < len(ts) and ts[k][0] == 'word' and name(ts[k]) in words
                and (k == 0 or ts[k - 1][1] != '.'))

    def group_boundary(k):
        if keyword(k, ('order',)):
            return keyword(k + 1, ('by',))
        if keyword(k, ('window',)):
            return keyword(k + 2, ('as',))
        if keyword(k, ('with',)):
            return keyword(k + 1, ('rollup',))
        return keyword(k, ('having', 'limit', 'into', 'for', 'lock'))

    changes = []
    for i in range(len(ts) - 1):
        if not keyword(i, ('group',)) or not keyword(i + 1, ('by',)):
            continue
        level = depths[i]
        query_end = next((k for k in range(i + 2, len(ts))
                          if depths[k] == level and
                          (ts[k][1] in (';', ')') or
                           keyword(k, ('union', 'except', 'intersect')))), len(ts))
        group_end = next((k for k in range(i + 2, query_end)
                          if depths[k] == level and group_boundary(k)), query_end)
        items, start = [], i + 2
        for k in range(start, group_end):
            if depths[k] == level and ts[k][1] == ',':
                items.append((start, k))
                start = k + 1
        items.append((start, group_end))
        for a, b in items:
            last = b - 1
            if (last <= a or depths[last] != level or ts[last][0] != 'word'
                    or name(ts[last]) != 'desc' or ts[last - 1][1] == '.'):
                continue
            # Remove DESC and adjacent whitespace, retaining every comment.
            gap = sql[ts[last - 1][3]:ts[last][2]]
            delete_start = ts[last - 1][3] if not gap.strip() else ts[last][2]
            changes.append((delete_start, ts[last][3], ''))
    return edit(sql, changes)


def transform(sql):
    sql = migrate_errors(sql)
    sql = convert_utf8_definitions(sql)
    sql = remove_group_by_desc(sql)
    ts, changes = lex(sql), []
    quoted = set(os.environ.get('QUOTE_IDENTIFIERS','over groups').lower().split())
    parens, windows = [], set()
    for i,t in enumerate(ts):
        prev = name(ts[i-1]) if i else ''
        after = name(ts[i+1]) if i+1 < len(ts) else ''
        w = name(t)
        if t[1] == '(':
            parens.append(i)
            if prev == 'over' and i >= 2 and ts[i-2][1] == ')':
                windows.add(i)
        elif t[1] == ')' and parens:
            windows.discard(parens.pop())
        if t[0] == 'word' and w == 'regexp' and after == 'binary' and ts[i+1][0] == 'word':
            changes.append((ts[i+1][2],ts[i+1][3],''))
        if t[0] != 'word' or w not in quoted:
            continue
        callable_words = {'rank','dense_rank','row_number','cume_dist','percent_rank',
                          'ntile','lag','lead','first_value','last_value','nth_value'}
        genuine = ((after == '(' and w in callable_words)
                   or (w == 'over' and prev == ')')
                   or (w == 'lateral' and after == '(')
                   or (w == 'recursive' and prev == 'with')
                   or (w == 'window' and i+2<len(ts) and name(ts[i+2]) == 'as')
                   or (w == 'groups' and windows and
                       (after in ('between','unbounded','current') or
                        (i+1<len(ts) and ts[i+1][0] == 'number'))))
        if not genuine:
            changes.append((t[2],t[3],BT+t[1]+BT))
    return edit(sql,changes)

def main():
    if len(sys.argv) not in (2,3):
        raise ValueError('Usage: --transform input.sql [output.sql]')
    source = Path(sys.argv[1])
    destination = Path(sys.argv[2]) if len(sys.argv) == 3 else source
    try:
        sql = source.read_bytes().decode('utf-8')
    except UnicodeDecodeError as error:
        raise ValueError(
            str(source) + ': invalid UTF-8 at byte ' + str(error.start)
            + '; re-export with --default-character-set=utf8mb4 and '
            + '--init-command="SET NAMES utf8mb4 COLLATE utf8mb4_general_ci"'
        ) from error
    result = transform(sql)
    descriptor, temporary = tempfile.mkstemp(prefix='.sql-transform-',dir=destination.parent)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='') as stream:
            stream.write(result)
        os.replace(temporary,destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

try:
    main()
except (ValueError,OSError) as error:
    print('SQL transformation failed: '+str(error),file=sys.stderr)
    sys.exit(1)
PY_SQL
}

if [[ "${1:-}" == "--transform" ]]; then
    shift
    transform_sql "$@"
    exit $?
fi
command -v python3 >/dev/null || { echo 'python3 is required' >&2; exit 1; }
PROCESS_SQL_SCRIPT_PATH="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/$(basename -- "${BASH_SOURCE[0]}")"
export PROCESS_SQL_SCRIPT_PATH

EXCLUDE_SQL="$(python3 - "$MAX_DIGITS_IN_NAME" "${#EXCLUDE_SP_PATTERNS[@]}" "${EXCLUDE_SP_PATTERNS[@]}" "${EXCLUDED_SCHEMAS[@]}" <<'PY_FILTER'
import sys
limit, count = int(sys.argv[1]), int(sys.argv[2])
if limit < 0:
    raise SystemExit('MAX_DIGITS_IN_NAME must be nonnegative')
literal = lambda value: "CONVERT(0x"+value.encode('utf-8').hex()+" USING utf8mb4)" if value else "''"
clauses = ['1=1']
clauses += ['a.ROUTINE_NAME NOT LIKE '+literal(p) for p in sys.argv[3:3+count]]
clauses += ['a.ROUTINE_SCHEMA <> '+literal(s) for s in sys.argv[3+count:]]
if limit:
    clauses.append("a.ROUTINE_NAME NOT REGEXP '[0-9]"+".*[0-9]"*(limit-1)+"'")
print(' AND '.join(clauses))
PY_FILTER
)" || exit 1


# Define SQL query based on the choice
SQL_QUERY=""

case $choice in
    1)
        # Option 1: Create all stored procedures and functions from all databases
	ALL_PROC_FILE="${MYSQL_HOST}_all_proc.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql --no-defaults --default-character-set=utf8mb4 --init-command=',CHAR(34),CHAR(36),'MYSQL_INIT_COMMAND',CHAR(34),' -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $PROC_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $PROC_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $PROC_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $PROC_FILE\n',
            'bash ',CHAR(34),CHAR(36),'PROCESS_SQL_SCRIPT_PATH',CHAR(34),' --transform ',CHAR(34),'$PROC_FILE',CHAR(34),CHAR(10),
            'cat $PROC_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a WHERE $EXCLUDE_SQL ORDER BY a.ROUTINE_SCHEMA, a.ROUTINE_NAME;"
        ;;
    2)
        # Option 2: Create only one specific stored procedure or function
        read -r -p "Enter the routine name: " ROUTINE_NAME
	read -r -p "Enter the database name: " DB_NAME
	OUTPUT_FILE="proc.sql" # Define custom output file based on host id, DB and routine name
	ALL_PROC_FILE="${MYSQL_HOST}_${DB_NAME}.${ROUTINE_NAME}.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql --no-defaults --default-character-set=utf8mb4 --init-command=',CHAR(34),CHAR(36),'MYSQL_INIT_COMMAND',CHAR(34),' -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $OUTPUT_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $OUTPUT_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $OUTPUT_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $OUTPUT_FILE\n',
            'bash ',CHAR(34),CHAR(36),'PROCESS_SQL_SCRIPT_PATH',CHAR(34),' --transform ',CHAR(34),'$OUTPUT_FILE',CHAR(34),CHAR(10),
            'cat $OUTPUT_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a 
        WHERE a.ROUTINE_NAME = '$ROUTINE_NAME' AND a.ROUTINE_SCHEMA = '$DB_NAME' AND ($EXCLUDE_SQL)
        LIMIT 1;"
        ;;
    3)
        # Option 3: Create all stored procedures and functions from a specific database
        read -r -p "Enter the database name: " DB_NAME
        OUTPUT_FILE="${DB_NAME}.sql" # Define custom output file based on DB name
        ALL_PROC_FILE="${MYSQL_HOST}_${DB_NAME}.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql --no-defaults --default-character-set=utf8mb4 --init-command=',CHAR(34),CHAR(36),'MYSQL_INIT_COMMAND',CHAR(34),' -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $OUTPUT_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $OUTPUT_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $OUTPUT_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $OUTPUT_FILE\n',
            'bash ',CHAR(34),CHAR(36),'PROCESS_SQL_SCRIPT_PATH',CHAR(34),' --transform ',CHAR(34),'$OUTPUT_FILE',CHAR(34),CHAR(10),
            'cat $OUTPUT_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a 
        WHERE a.ROUTINE_SCHEMA = '$DB_NAME' AND ($EXCLUDE_SQL)
        ORDER BY a.ROUTINE_NAME;"
        ;;
    *)
        echo "Invalid choice!"
        exit 1
        ;;
esac

# Execute the query and write commands to the temporary file
mysql --no-defaults --default-character-set=utf8mb4 --init-command="$MYSQL_INIT_COMMAND" -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -e "$SQL_QUERY" --silent --raw --skip-column-names > $TEMP_CMD_FILE

# Execute the generated export commands, stopping if a transformation fails.
bash -e "$TEMP_CMD_FILE"

# Clean up temporary command file
rm -f $TEMP_CMD_FILE

rm -f $PROC_FILE

rm -f $OUTPUT_FILE

