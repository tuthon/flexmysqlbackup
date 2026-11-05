import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'flexmysqlbackup.sh'
spec=importlib.util.spec_from_file_location('launcher',ROOT/'src/launcher.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.RESOURCES={p.name:p.read_text() for p in (ROOT/'src/sql').glob('*.sql')}
module.RESOURCES['transformer.py']=(ROOT/'src/transformer.py').read_text()


class Integration(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='flex-tests-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.bin=self.root/'bin'
        self.bin.mkdir()
        for name in ('mysql','mysqldump'):
            shutil.copy(ROOT/'tests/fake_mysql.py',self.bin/name)
            (self.bin/name).chmod(0o700)
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],FLEX_TEST_ROOT=str(self.root))
        self.output=self.root/'backups with spaces'
        (self.root/'installed.json').write_text(json.dumps(list(module.GENERATORS)))

    def run_menu(self, answers, **env):
        result=subprocess.run(['bash',str(SCRIPT),'--host','source.invalid','--port','3307',
                               '--user','tester','--output',str(self.output)],
                              input='test-secret\n'+answers, text=True,capture_output=True,
                              env=dict(self.env,**env),timeout=15)
        self.assertEqual(result.returncode,0,(result.stdout,result.stderr))
        return result

    def calls(self):
        return [json.loads(line) for line in (self.root/'calls.jsonl').read_text().splitlines()]

    def test_every_export_menu_and_real_sed(self):
        result=self.run_menu('1\n1\n2\n3\nfixture\nt\n\n\n\n3\n2\nfixture\nInnoDB\n'
                             '4\n2\nfixture\n5\n3\nfixture\nnormal\n1\n6\n1\n7\n1\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        files=list(self.output.glob('*/*.sql'))
        self.assertEqual(len(files),7)
        table=next(p for p in files if p.name=='tables.sql').read_text()
        self.assertIn('\nCREATE TABLE',table)
        self.assertNotIn('TablesScript',table)
        self.assertNotIn(r'\n',table)
        routine=next(p for p in files if p.name=='routines.sql').read_text()
        self.assertIn('@errNom',routine)
        self.assertIn('DECLARE rowNo',routine)
        self.assertNotIn('REGEXP BINARY',routine)
        self.assertIn('GROUP BY `over`;',routine)
        self.assertNotIn('ORDER BY',routine)
        self.assertIn('Кирилица 😀',routine)
        calls=self.calls()
        dump=next(c for c in calls if c['program']=='mysqldump' and '--help' not in c['args'])
        self.assertEqual(dump['args'][-3:],['--','fixture','t'])
        self.assertIn('--host=source.invalid',dump['args'])
        self.assertIn('--column-statistics=0',dump['args'])
        self.assertNotIn('--databases',dump['args'])
        for call in calls:
            self.assertTrue(call['password_present'])
            self.assertNotIn('test-secret',str(call['args']))
            self.assertEqual(call['args'][0],'--no-defaults')
            self.assertNotIn('--xml',call['args'])
        for p in files:
            self.assertEqual(p.stat().st_mode & 0o077,0)
        self.assertFalse((self.root/'installer.sql').exists())

    def test_missing_generator_installs_only_needed(self):
        (self.root/'installed.json').write_text('[]')
        result=self.run_menu('1\n1\ny\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        self.assertEqual(json.loads((self.root/'installed.json').read_text()),['gen_schemes_script'])
        sql=(self.root/'installer.sql').read_text()
        self.assertIn('CREATE DATABASE IF NOT EXISTS',sql)
        self.assertIn('CREATE DEFINER=CURRENT_USER PROCEDURE',sql)
        self.assertIn('RESIGNAL;',sql)
        self.assertNotIn('SELECT errNom, errText;',sql)

    def test_decline_install_does_not_write(self):
        (self.root/'installed.json').write_text('[]')
        result=self.run_menu('1\n1\nn\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        self.assertFalse(self.output.exists())
        self.assertFalse((self.root/'installer.sql').exists())

    def test_explicit_update_contains_six_helpers_only(self):
        result=self.run_menu('8\n2\ny\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        sql=(self.root/'installer.sql').read_text()
        self.assertEqual(sql.count('CREATE DEFINER=CURRENT_USER PROCEDURE'),6)
        self.assertIn('SchemaNames TEXT CHARACTER SET utf8mb4',sql)
        self.assertNotIn('DROP DATABASE',sql)
        self.assertIn('CREATE DEFINER=`Sup_User_SPESA`@`%` EVENT',sql)

    def test_generator_failure_does_not_create_sql_file(self):
        result=self.run_menu('1\n1\n0\n',FLEX_FAIL_CALL='1')
        self.assertIn('fixture generator failed',result.stderr)
        self.assertFalse(self.output.exists())

    def test_legacy_swallowed_error_is_not_a_backup(self):
        result=self.run_menu('1\n1\n0\n',FLEX_DIAGNOSTIC='1')
        self.assertIn('returned diagnostics',result.stderr)
        self.assertFalse(self.output.exists())

    def test_failed_install_does_not_export(self):
        (self.root/'installed.json').write_text('[]')
        result=self.run_menu('1\n1\ny\n0\n',FLEX_FAIL_INSTALL='1')
        self.assertIn('CREATE ROUTINE denied',result.stderr)
        self.assertFalse(self.output.exists())

    def test_dump_failure_removes_partial_file(self):
        result=self.run_menu('3\n2\nfixture\nInnoDB\n0\n',FLEX_FAIL_DUMP='1')
        self.assertIn('fixture dump failed',result.stderr)
        self.assertEqual(list(self.output.glob('*/*')),[])

    def test_original_routines_and_filters(self):
        result=self.run_menu('5\n1\n2\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        sql=next(self.output.glob('*/routines.sql')).read_text()
        self.assertIn('REGEXP BINARY',sql)
        self.assertIn('GROUP BY over DESC',sql)
        self.assertIn('PROCEDURE `p1234`',sql)
        self.assertNotIn('PROCEDURE `p12345`',sql)
        self.assertNotIn('PROCEDURE `p_copy`',sql)
        self.assertIn('FUNCTION `function_name`',sql)
        query=next(c for c in self.calls() if 'FROM information_schema.ROUTINES WHERE' in str(c['args']))
        for pattern in module.DEFAULT_PATTERNS:
            self.assertIn(pattern.encode().hex(),str(query['args']))
        self.assertIn("ROUTINE_NAME NOT REGEXP '[0-9].*[0-9].*[0-9].*[0-9].*[0-9]'",str(query['args']))

    def test_routine_exclusions_are_configurable(self):
        result=self.run_menu('5\n2\nfixture\n1\n0\n',EXCLUDE_SP_PATTERNS_JSON='[]',
                             EXCLUDED_SCHEMAS_JSON='["legacy"]',MAX_DIGITS_IN_NAME='0')
        self.assertNotIn('ERROR:',result.stderr)
        query=next(c for c in self.calls() if 'FROM information_schema.ROUTINES WHERE' in str(c['args']))
        self.assertNotIn('ROUTINE_NAME NOT LIKE',str(query['args']))
        self.assertNotIn('ROUTINE_NAME NOT REGEXP',str(query['args']))
        self.assertIn('ROUTINE_SCHEMA<>CONVERT(0x6c6567616379 USING utf8mb4)',str(query['args']))

    def test_table_target_charset_pair_reaches_generator(self):
        result=self.run_menu('2\n2\nfixture\nInnoDB\nutf8mb4\nutf8mb4_general_ci\n0\n')
        self.assertNotIn('ERROR:',result.stderr)
        query=next(c for c in self.calls() if 'CALL tools.gen_table_script' in str(c['args']))
        for value in ('fixture','InnoDB','utf8mb4','utf8mb4_general_ci'):
            self.assertIn(value.encode().hex(),str(query['args']))

    def test_shell_characters_in_engine_are_rejected(self):
        result=self.run_menu('2\n1\nInnoDB"; DROP TABLE x;\n0\n')
        self.assertIn('Engine must contain',result.stderr)
        self.assertFalse(self.output.exists())

    def test_connection_failure_stops_before_main_menu(self):
        result=subprocess.run(['bash',str(SCRIPT),'--host','source.invalid','--port','3307',
                               '--user','tester','--output',str(self.output)],
                              input='test-secret\n',text=True,capture_output=True,
                              env=dict(self.env,FLEX_FAIL_QUERY='1'),timeout=5)
        self.assertEqual(result.returncode,1)
        self.assertIn('fixture access denied',result.stderr)
        self.assertNotIn('1. Schemas (databases)',result.stdout)

    def test_repeated_exports_never_append_or_overwrite(self):
        self.run_menu('1\n1\n1\n1\n0\n')
        files=list(self.output.glob('*/schemas.sql'))
        self.assertEqual(len(files),2)
        self.assertEqual(files[0].read_bytes(),files[1].read_bytes())

    def test_safe_selection_does_not_become_shell(self):
        hostile="'; touch HACKED; #"
        self.run_menu('4\n3\nfixture\n'+hostile+'\n0\n')
        self.assertFalse((ROOT/'HACKED').exists())
        query=next(c for c in self.calls() if '--execute' in c['args']
                   and 'CALL' in str(c['args']))
        self.assertNotIn(hostile,str(query['args']))
        self.assertIn(hostile.encode().hex(),str(query['args']))

    def test_offline_runs_without_connection_or_credentials(self):
        source=self.root/'input.sql'
        output=self.root/'output.sql'
        source.write_text('SELECT a FROM t GROUP BY a DESC;')
        result=subprocess.run(['bash',str(SCRIPT),'--transform',str(source),str(output)],
                              capture_output=True,text=True,env=self.env,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(output.read_text(),'SELECT a FROM t GROUP BY a;')
        self.assertFalse((self.root/'calls.jsonl').exists())
        self.assertNotIn('password',result.stdout)

    def test_invalid_utf8_does_not_overwrite_output(self):
        source=self.root/'input.sql'
        output=self.root/'output.sql'
        source.write_bytes(b'bad\x96text')
        output.write_text('keep me')
        result=subprocess.run(['bash',str(SCRIPT),'--transform',str(source),str(output)],
                              capture_output=True,text=True,env=self.env,timeout=5)
        self.assertEqual(result.returncode,1)
        self.assertEqual(output.read_text(),'keep me')
        self.assertIn('utf-8',result.stderr)

    def test_extract_installer_without_mysql(self):
        output=self.root/'installer-output.sql'
        result=subprocess.run(['bash',str(SCRIPT),'--extract-install-sql',str(output)],
                              capture_output=True,text=True,env=self.env,timeout=5)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(output.read_text().count('CREATE DEFINER=CURRENT_USER PROCEDURE'),6)
        self.assertFalse((self.root/'calls.jsonl').exists())

    def test_one_time_event_cannot_be_silently_omitted(self):
        result=self.run_menu('7\n1\n0\n',FLEX_ONE_TIME_EVENT='1')
        self.assertIn('cannot export one-time events',result.stderr)
        self.assertIn('fixture.one_time_event',result.stderr)
        self.assertFalse(self.output.exists())

    def test_original_complex_routine_is_preserved_byte_for_byte_without_xml(self):
        result=self.run_menu('5\n3\nfixture\nnormal\n2\n0\n',FLEX_COMPLEX_BODY='1')
        self.assertNotIn('ERROR:',result.stderr)
        actual=next(self.output.glob('*/routines.sql')).read_bytes()
        expected=(self.root/'expected-body.sql').read_bytes()
        self.assertIn(expected,actual)
        self.assertIn(b'\x0b\x1a\x00',actual)
        for call in self.calls():
            self.assertNotIn('--xml',call['args'])

    def test_transformed_complex_routine_is_lossless_outside_requested_changes(self):
        result=self.run_menu('5\n3\nfixture\nnormal\n1\n0\n',FLEX_COMPLEX_BODY='1')
        self.assertNotIn('ERROR:',result.stderr)
        actual=next(self.output.glob('*/routines.sql')).read_bytes()
        self.assertIn(b'\x0b\x1a\x00',actual)
        self.assertIn(b'CR: \r; markup: <tag> &value;',actual)
        self.assertIn(br"SELECT '\n', '\t', '\\', '\0', '\r';",actual)
        self.assertIn('Кирилица 😀'.encode(),actual)
        self.assertIn(b'@errNom',actual)
        self.assertNotIn(b'GROUP BY over DESC',actual)

    def test_batch_failure_identifies_routine_and_removes_partial_export(self):
        result=self.run_menu('5\n3\nfixture\nnormal\n1\n0\n',FLEX_BROKEN_BATCH='1')
        self.assertIn('Reading PROCEDURE `fixture`.`normal`',result.stderr)
        self.assertIn('expected columns',result.stderr)
        self.assertEqual(list(self.output.glob('*/*')),[])

    def test_event_export_restores_tabs_and_keeps_sql_literal_escapes(self):
        body = ("DROP EVENT IF EXISTS `fixture`.`event1`;\nDELIMITER $$\n"
                "CREATE EVENT `fixture`.`event1` ON SCHEDULE EVERY 1 DAY DISABLE DO\nBEGIN\n"
                "\t-- Кирилица 😀\n\tSELECT " + r"'\n', '\t', '\\', '\0', '\r', '\\n';"
                + "\n\tCALL fixture.procedure1();\nEND$$\nDELIMITER ;\n")
        fixture=self.root/'definition.sql'
        fixture.write_bytes(body.encode('utf-8'))
        result=self.run_menu('7\n1\n0\n',FLEX_DEFINITION_BODY=str(fixture))
        self.assertNotIn('ERROR:',result.stderr)
        actual=next(self.output.glob('*/events.sql')).read_bytes()
        self.assertEqual(actual,body.encode('utf-8'))
        self.assertNotIn(br'\tCALL',actual)

    def test_all_generated_definition_types_decode_batch_fields(self):
        body="USE `fixture`;\n\t-- tabbed comment\nSELECT " + r"'\n', '\t', '\\';" + "\n"
        fixture=self.root/'definition.sql'
        fixture.write_bytes(body.encode())
        result=self.run_menu('1\n1\n2\n3\nfixture\nt\n\n\n\n4\n1\n6\n1\n7\n1\n0\n',
                             FLEX_DEFINITION_BODY=str(fixture))
        self.assertNotIn('ERROR:',result.stderr)
        files=list(self.output.glob('*/*.sql'))
        self.assertEqual(len(files),5)
        for path in files:
            self.assertEqual(path.read_bytes(),body.encode())

    def test_multiple_generator_rows_preserve_separate_definitions(self):
        fixture=self.root/'definition.sql'
        fixture.write_bytes(b'CREATE VIEW `fixture`.`v` AS SELECT 1;')
        result=self.run_menu('4\n1\n0\n',FLEX_DEFINITION_BODY=str(fixture),FLEX_MULTI_DEFINITIONS='1')
        self.assertNotIn('ERROR:',result.stderr)
        actual=next(self.output.glob('*/views.sql')).read_bytes()
        self.assertEqual(actual,fixture.read_bytes()+b'\n'+fixture.read_bytes()+b'\n')

    def test_generator_extra_columns_are_not_saved_as_sql(self):
        fixture=self.root/'definition.sql'
        fixture.write_bytes(b'SELECT 1;')
        result=self.run_menu('7\n1\n0\n',FLEX_DEFINITION_BODY=str(fixture),FLEX_MULTI_RESULT_COLUMNS='1')
        self.assertIn('expected one SQL result column',result.stderr)
        self.assertFalse(self.output.exists())


class BatchParsing(unittest.TestCase):
    def test_literal_backslash_sequences_are_decoded_once(self):
        wire = 'name\tbody\nnormal\t' + r"SELECT '\\n', '\\t', '\\\\', '\\0', '\\r', '\\u0041';" + '\n'
        body=module.parse_batch_rows(wire,'fixture')[0]['body']
        self.assertEqual(body,r"SELECT '\n', '\t', '\\', '\0', '\r', '\u0041';")

    def test_batch_escapes_and_xml_forbidden_controls(self):
        wire = 'body\n' + r'first\nsecond\tthird\0fourth\\' + '\x0b\x1a\r\x85\u2028\u2029\n'
        self.assertEqual(module.parse_batch_rows(wire,'fixture')[0]['body'],
                         'first\nsecond\tthird\0fourth\\\x0b\x1a\r\x85\u2028\u2029')

    def test_empty_results(self):
        self.assertEqual(module.parse_batch_rows('','fixture'),[])
        self.assertEqual(module.parse_batch_rows('name\n','fixture'),[])
        self.assertEqual(module.parse_batch_rows('name','fixture'),[])

    def test_empty_fields_and_literal_NULL_name(self):
        self.assertEqual(module.parse_batch_rows('name\tbody\nNULL\t\n','fixture'),
                         [{'name':'NULL','body':''}])

    def test_malformed_rows_fail_with_context(self):
        with self.assertRaisesRegex(module.BackupError,'fixture: invalid mysql --batch row 1'):
            module.parse_batch_rows('name\tbody\nnormal\tpart\tunescaped\n','fixture')

    def test_header_mismatch_fails_with_context(self):
        with self.assertRaisesRegex(module.BackupError,'fixture: mysql --batch did not return expected columns'):
            module.parse_batch_rows('unexpected\nvalue\n','fixture',('ROUTINE_NAME',))

    def test_duplicate_headers_fail(self):
        with self.assertRaisesRegex(module.BackupError,'invalid column headers'):
            module.parse_batch_rows('name\tname\na\tb\n','fixture')


if __name__=='__main__':
    unittest.main()
