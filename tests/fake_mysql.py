#!/usr/bin/env python3
"""Protocol fixture, not a SQL engine. Never connects to a server."""
import json
import os
from pathlib import Path
import re
import sys

args = sys.argv[1:]
root = Path(os.environ['FLEX_TEST_ROOT'])
with (root/'calls.jsonl').open('a') as f:
    f.write(json.dumps({'program':Path(sys.argv[0]).name, 'args':args,
                        'password_present':os.environ.get('MYSQL_PWD') == 'test-secret'})+'\n')
if Path(sys.argv[0]).name == 'mysqldump':
    if '--help' in args:
        print('mysqldump supports --column-statistics')
    elif os.environ.get('FLEX_FAIL_DUMP'):
        print('fixture dump failed',file=sys.stderr)
        sys.exit(2)
    else:
        print("INSERT INTO `fixture` VALUES (1, 'Кирилица 😀');")
    sys.exit(0)
state = root/'installed.json'
installed = json.loads(state.read_text()) if state.exists() else []
if '--execute' not in args:
    sql=sys.stdin.read()
    (root/'installer.sql').write_text(sql)
    if os.environ.get('FLEX_FAIL_INSTALL'):
        print('fixture CREATE ROUTINE denied',file=sys.stderr)
        sys.exit(1)
    names=re.findall(r'CREATE DEFINER=CURRENT_USER PROCEDURE (?:`tools`\.)?`([^`]+)`',sql)
    state.write_text(json.dumps(sorted(set(installed+names))))
    sys.exit(0)
sql=args[args.index('--execute')+1]
if os.environ.get('FLEX_FAIL_QUERY'):
    print('fixture access denied',file=sys.stderr)
    sys.exit(1)

def batch(rows):
    if not rows:
        # mysql may produce no bytes for an empty result set.
        return
    columns=list(rows[0])
    if os.environ.get('FLEX_BROKEN_BATCH') and sql.startswith('SHOW CREATE'):
        print('bad_header\ntruncated')
        return
    def encode(value):
        if value is None:
            return 'NULL'
        return (value.replace('\\','\\\\').replace('\0','\\0')
                .replace('\t','\\t').replace('\n','\\n'))
    print('\t'.join(columns))
    for row in rows:
        print('\t'.join(encode(row[k]) for k in columns))

def conditions(column, default=''):
    pattern = column+r'\s*=CONVERT\(0x([0-9a-f]+) USING utf8mb4\)'
    match = re.search(pattern,sql,re.I)
    return bytes.fromhex(match[1]).decode() if match else default

if 'SELECT VERSION()' in sql:
    batch([{'version':'8.4.fixture','account':'tester@fixture'}])
elif "ROUTINE_SCHEMA='tools'" in sql:
    batch([{'ROUTINE_NAME':name} for name in installed])
elif 'FROM information_schema.ROUTINES WHERE' in sql:
    rows=[]
    for name in ('normal','p1234','p12345','p_copy','function_name'):
        if name.endswith('copy') or len(re.sub('[^0-9]','',name))>=5:
            continue
        if conditions('ROUTINE_NAME', name) != name:
            continue
        if conditions('ROUTINE_SCHEMA','fixture') != 'fixture':
            continue
        rows.append({'ROUTINE_SCHEMA':'fixture','ROUTINE_NAME':name,
                     'ROUTINE_TYPE':'FUNCTION' if name=='function_name' else 'PROCEDURE'})
    batch(rows)
elif sql.startswith('SHOW CREATE'):
    kind=sql.split()[2]
    name=sql.rsplit('`',2)[1]
    if kind=='FUNCTION':
        body=f'CREATE DEFINER=`owner`@`%` FUNCTION `{name}`() RETURNS INT DETERMINISTIC RETURN 1'
    else:
        body=f'''CREATE DEFINER=`owner`@`%` PROCEDURE `{name}`() BEGIN
DECLARE errNom,rowNo INT DEFAULT 0;
DECLARE errText VARCHAR(100) CHARSET utf8;
DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
GET DIAGNOSTICS CONDITION 1 errNom=MYSQL_ERRNO,errText=MESSAGE_TEXT;
INSERT INTO tools.error_log(err_no,err_text,row_no) VALUES(errNom,errText,rowNo);
END;
-- Кирилица 😀
SELECT over FROM t WHERE s REGEXP BINARY 'x' GROUP BY over DESC;
END'''
    if os.environ.get('FLEX_COMPLEX_BODY'):
        body += "\n-- XML controls: \x0b\x1a\x00; Unicode: Кирилица 😀; CR: \r; markup: <tag> &value;\n"
        body += r"SELECT '\n', '\t', '\\', '\0', '\r';" + "\n"
        body += "-- actual tabs: \t\t; line separators: \x85\u2028\u2029\n"
        (root/'expected-body.sql').write_bytes(body.encode('utf-8'))
    batch([{'Create '+kind.title():body}])
elif 'FROM information_schema.COLLATIONS' in sql:
    batch([{'COLLATION_NAME':'utf8mb4_general_ci'}])
elif 'FROM information_schema.SCHEMATA' in sql:
    batch([{'SCHEMA_NAME':'fixture'}])
elif 'FROM information_schema.EVENTS' in sql:
    batch([{'EVENT_SCHEMA':'fixture','EVENT_NAME':'one_time_event'}] if os.environ.get('FLEX_ONE_TIME_EVENT') else [])
elif 'FROM information_schema.TABLES' in sql:
    rows=[{'TABLE_SCHEMA':'fixture','TABLE_NAME':'t','ENGINE':'InnoDB'},
          {'TABLE_SCHEMA':'fixture','TABLE_NAME':'other','ENGINE':'MyISAM'}]
    rows=[r for r in rows if all(conditions(k,v)==v for k,v in r.items())]
    batch(rows)
elif sql.startswith('CALL'):
    if os.environ.get('FLEX_FAIL_CALL'):
        print('fixture generator failed',file=sys.stderr)
        sys.exit(1)
    name=sql.split('(')[0].split('.')[-1]
    if os.environ.get('FLEX_DIAGNOSTIC'):
        print('errNom\terrText\n1064\tfixture SQL error')
    elif name=='gen_schemes_script':
        print('CONCAT(...)\nCREATE DATABASE IF NOT EXISTS `fixture`;')
    elif name=='gen_table_script':
        print(r"TablesScript"+'\n'+r"USE `fixture`;\nCREATE TABLE `t` (`id` int);\n")
    else:
        print('fullscript\n'+r"USE `fixture`;\nSELECT 'Кирилица 😀';\n")
else:
    print('Unexpected fixture query: '+sql,file=sys.stderr)
    sys.exit(4)
