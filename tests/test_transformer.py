import itertools
import os
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'flexmysqlbackup.sh'
namespace = {'__name__': 'transformer'}
exec((ROOT / 'src/transformer.py').read_text(), namespace)
transform = namespace['transform']
os.environ['QUOTE_IDENTIFIERS'] = 'over groups rank dense_rank row_number cume_dist percent_rank ntile lag lead first_value last_value nth_value recursive window lateral'

def words(sql):
    return [namespace['name'](t) for t in namespace['lex'](sql)]

class Tests(unittest.TestCase):
    def test_group_by_user_examples(self):
        sql='''IF flag = 13 THEN
SELECT CASE WHEN r.added_from = 200110 THEN 'Milele radio'
WHEN r.added_from = 200111 THEN 'Jambo Radio'
WHEN r.added_from = 200112 THEN 'KISS Radio' END as `name`,
r.date_reg as `DATE`, count(r.user_id) as `REG(#)`,
format(sum(IF(r.with_bet = 0,1,0)),0) as `W/0(#)`
FROM _radio r GROUP BY r.date_reg DESC;
END IF;'''
        expected=sql.replace('GROUP BY r.date_reg DESC;',
                             'GROUP BY r.date_reg;')
        self.assertEqual(transform(sql),expected)
        sql="SELECT type_prom,enbl,start_date,concat(end_date,' 23:59:59') INTO TypeProm,Enabl,StartDate,EndDate FROM bis.promotions WHERE type_prom=26 GROUP BY id DESC LIMIT 1;"
        expected=sql.replace('GROUP BY id DESC LIMIT 1;',
                             'GROUP BY id LIMIT 1;')
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_group_by_mixed_columns(self):
        sql='SELECT a,b,c FROM t GROUP BY a DESC, b ASC, c LIMIT 2;'
        expected='SELECT a,b,c FROM t GROUP BY a, b ASC, c LIMIT 2;'
        self.assertEqual(transform(sql),expected)

    def test_group_by_existing_order_by(self):
        sql='SELECT a,b FROM t GROUP BY a DESC, b ASC HAVING count(*)>1 ORDER BY b DESC LIMIT 1;'
        expected='SELECT a,b FROM t GROUP BY a, b ASC HAVING count(*)>1 ORDER BY b DESC LIMIT 1;'
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_group_by_having_window_and_locking(self):
        sql='SELECT a FROM t GROUP BY a DESC HAVING count(*)>1 LIMIT 1 FOR UPDATE;'
        expected='SELECT a FROM t GROUP BY a HAVING count(*)>1 LIMIT 1 FOR UPDATE;'
        self.assertEqual(transform(sql),expected)
        sql='SELECT a,ROW_NUMBER() OVER w FROM t GROUP BY a DESC WINDOW w AS (ORDER BY a);'
        expected='SELECT a,ROW_NUMBER() OVER w FROM t GROUP BY a WINDOW w AS (ORDER BY a);'
        self.assertEqual(transform(sql),expected)

    def test_group_by_subqueries_and_functions(self):
        sql='SELECT x FROM (SELECT x FROM t GROUP BY x DESC LIMIT 1) d GROUP BY x ASC;'
        expected='SELECT x FROM (SELECT x FROM t GROUP BY x LIMIT 1) d GROUP BY x ASC;'
        self.assertEqual(transform(sql),expected)
        sql='SELECT a FROM t GROUP BY COALESCE(a,b) DESC, DATE(dt) ASC;'
        expected='SELECT a FROM t GROUP BY COALESCE(a,b), DATE(dt) ASC;'
        self.assertEqual(transform(sql),expected)

    def test_group_by_subquery_inside_group_expression(self):
        sql='SELECT a FROM t GROUP BY (SELECT max(b) FROM q GROUP BY b DESC LIMIT 1) DESC;'
        expected='SELECT a FROM t GROUP BY (SELECT max(b) FROM q GROUP BY b LIMIT 1);'
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_group_by_comments_strings_and_eof(self):
        sql="SELECT 'GROUP BY a DESC' FROM t GROUP BY a /*keep*/ DESC; -- GROUP BY b DESC\n"
        expected="SELECT 'GROUP BY a DESC' FROM t GROUP BY a /*keep*/ ; -- GROUP BY b DESC\n"
        self.assertEqual(transform(sql),expected)
        sql='SELECT a FROM t GROUP BY a DESC -- keep at end'
        expected='SELECT a FROM t GROUP BY a -- keep at end'
        self.assertEqual(transform(sql),expected)

    def test_group_by_qualified_keyword_columns(self):
        sql='SELECT t.desc FROM t GROUP BY t.desc, t.order DESC, t.limit ASC;'
        expected='SELECT t.desc FROM t GROUP BY t.desc, t.order, t.limit ASC;'
        self.assertEqual(transform(sql),expected)
        sql='SELECT window FROM t GROUP BY window DESC;'
        expected='SELECT `window` FROM t GROUP BY `window`;'
        self.assertEqual(transform(sql),expected)

    def test_group_by_no_legacy_order_unchanged(self):
        for sql in ['SELECT a FROM t GROUP BY a;',
                    'SELECT a FROM t GROUP BY a ASC;',
                    'SELECT a FROM t GROUP BY a ORDER BY a DESC;',
                    'SELECT t.desc FROM t GROUP BY t.desc;',
                    'SELECT `desc` FROM t GROUP BY `desc`;',
                    "SET @sql='SELECT a FROM t GROUP BY a DESC';"]:
            self.assertEqual(transform(sql),sql)

    def test_group_by_fix_option(self):
        old=os.environ.get('REMOVE_GROUP_BY_DESC')
        try:
            os.environ['REMOVE_GROUP_BY_DESC']='0'
            sql='SELECT a FROM t GROUP BY a DESC;'
            self.assertEqual(transform(sql),sql)
        finally:
            if old is None:
                os.environ.pop('REMOVE_GROUP_BY_DESC',None)
            else:
                os.environ['REMOVE_GROUP_BY_DESC']=old

    def test_group_by_rollup(self):
        sql='SELECT a,count(*) FROM t GROUP BY a DESC WITH ROLLUP;'
        expected='SELECT a,count(*) FROM t GROUP BY a WITH ROLLUP;'
        self.assertEqual(transform(sql),expected)

    def test_group_by_parenthesized_union(self):
        sql='(SELECT a FROM t GROUP BY a DESC LIMIT 1) UNION ALL (SELECT a FROM q GROUP BY a ASC LIMIT 1);'
        expected='(SELECT a FROM t GROUP BY a LIMIT 1) UNION ALL (SELECT a FROM q GROUP BY a ASC LIMIT 1);'
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform('SELECT a FROM t GROUP BY a DESC UNION ALL SELECT a FROM q;'),
                         'SELECT a FROM t GROUP BY a UNION ALL SELECT a FROM q;')

    def test_user_create_table_examples(self):
        sql='''IF act=99 THEN
CREATE TABLE IF NOT EXISTS bets.b_bet_reset(
    bet_id BIGINT(20) UNSIGNED NOT NULL DEFAULT '0',
    PRIMARY KEY (bet_id)
    ) ENGINE = MyISAM DEFAULT CHARSET=utf8;
END IF;
DECLARE CONTINUE HANDLER FOR 1146
BEGIN
    -- table doesn't exists, do something...
    CREATE TABLE billing.mpesa_ipn_queue (
      `id` int(11) unsigned NOT NULL AUTO_INCREMENT,
      `date_in` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
      `user_id` bigint(20) unsigned NOT NULL DEFAULT '0',
      `receipt_id` varchar(20) NOT NULL DEFAULT '',
      `deposit_amount` int(11) NOT NULL DEFAULT '0',
      `details` varchar(255) NOT NULL DEFAULT '',
      `user_name` varchar(80) NOT NULL DEFAULT '',
      `insert_time` timestamp NOT NULL DEFAULT '0000-00-00 00:00:00' COMMENT 'datetime of insert into this table',
      `source_id` tinyint(4) NOT NULL DEFAULT '0',
      `status` varchar(30) NOT NULL DEFAULT '',
      `utl_acc` int(11) unsigned NOT NULL DEFAULT '0',
      PRIMARY KEY (`id`),
      UNIQUE KEY `receipt_idx` (`receipt_id`) USING BTREE
    ) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8 COLLATE=utf8_general_ci COMMENT='Store MPESA IPN deposits';
END;'''
        expected=sql.replace('DEFAULT CHARSET=utf8','DEFAULT CHARSET=utf8mb4').replace('COLLATE=utf8_general_ci','COLLATE=utf8mb4_general_ci')
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_create_table_column_and_option_variants(self):
        for charset in ('utf8','utf8mb3','utf8mb4'):
            for keyword in ('CHARSET=', 'CHARSET ', 'CHARACTER SET = ', 'CHARACTER SET '):
                with self.subTest(charset=charset,keyword=keyword):
                    sql=('CREATE TEMPORARY TABLE IF NOT EXISTS `db`.`t` ('
                         'a VARCHAR(20) '+keyword+charset+' COLLATE '+charset+'_unicode_ci,'
                         'e ENUM(\'a,b\',\'c\') '+keyword+charset+') '
                         'ENGINE=InnoDB DEFAULT '+keyword+charset+' COLLATE='+charset+'_general_ci;')
                    expected=('CREATE TEMPORARY TABLE IF NOT EXISTS `db`.`t` ('
                              'a VARCHAR(20) '+keyword+'utf8mb4 COLLATE utf8mb4_unicode_ci,'
                              'e ENUM(\'a,b\',\'c\') '+keyword+'utf8mb4) '
                              'ENGINE=InnoDB DEFAULT '+keyword+'utf8mb4 COLLATE=utf8mb4_general_ci;')
                    self.assertEqual(transform(sql),expected)

    def test_create_table_comments_and_defaults(self):
        sql='''CREATE TABLE t(
a VARCHAR(50) CHARACTER /*keep*/ SET utf8 DEFAULT 'CHARSET=utf8' COMMENT 'COLLATE=utf8_bin',
b VARCHAR(10) DEFAULT '' COLLATE utf8_general_ci,
c TEXT /*CHARSET utf8*/
) ENGINE=MyISAM DEFAULT CHARACTER SET /*keep2*/ = utf8 COLLATE = utf8_unicode_ci COMMENT='DEFAULT CHARSET=utf8';'''
        expected=sql.replace('SET utf8 DEFAULT','SET utf8mb4 DEFAULT').replace("DEFAULT '' COLLATE utf8_general_ci", "DEFAULT '' COLLATE utf8mb4_general_ci").replace('= utf8 COLLATE = utf8_unicode_ci','= utf8mb4 COLLATE = utf8mb4_unicode_ci')
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_create_table_expressions_select_and_like(self):
        sql='''CREATE TABLE t(a VARCHAR(10) CHARSET utf8 DEFAULT ('x' COLLATE utf8_bin),
b TEXT CHARSET utf8 AS (a COLLATE utf8_bin)) DEFAULT CHARSET=utf8;
CREATE TABLE t2 DEFAULT CHARSET=utf8 AS SELECT x COLLATE utf8_bin FROM t;
CREATE TABLE t3 LIKE t;
CREATE TABLE t4 AS SELECT 'DEFAULT CHARSET=utf8' AS x;'''
        expected=sql.replace('CHARSET utf8 DEFAULT','CHARSET utf8mb4 DEFAULT').replace('CHARSET utf8 AS','CHARSET utf8mb4 AS').replace('DEFAULT CHARSET=utf8;','DEFAULT CHARSET=utf8mb4;').replace('DEFAULT CHARSET=utf8 AS','DEFAULT CHARSET=utf8mb4 AS')
        self.assertEqual(transform(sql),expected)

    def test_existing_utf8mb4_table_unchanged(self):
        sql='CREATE TABLE t(a VARCHAR(10) CHARSET utf8mb4 COLLATE utf8mb4_bin) DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;'
        self.assertEqual(transform(sql),sql)

    def test_non_utf8_table_unchanged(self):
        sql='CREATE TABLE t(a VARCHAR(10) CHARSET latin1 COLLATE latin1_swedish_ci) DEFAULT CHARSET=latin1;'
        self.assertEqual(transform(sql),sql)

    def test_dynamic_create_table_string_is_preserved(self):
        sql="SET @sql='CREATE TABLE t(a TEXT) DEFAULT CHARSET=utf8'; /* CREATE TABLE t2(a TEXT) CHARSET=utf8; */"
        self.assertEqual(transform(sql),sql)

    def test_table_collation_requires_known_mapping(self):
        sql='CREATE TABLE t(a TEXT) DEFAULT CHARSET=utf8 COLLATE=utf8_general_mysql500_ci;'
        with self.assertRaisesRegex(ValueError,'No verified utf8mb4 equivalent'):
            transform(sql)

    def test_existing_utf8mb4_function_header(self):
        sql='CREATE DEFINER=`Sup_User_SPESA`@`%` FUNCTION `bet_encode36`(`num_id` int unsigned) RETURNS varchar(8) CHARSET utf8mb4'
        self.assertEqual(transform(sql),sql)
        sql+=' COLLATE utf8mb4_0900_ai_ci DETERMINISTIC RETURN \'a\';'
        self.assertEqual(transform(sql),sql)

    def test_known_utf8_collation_conversion(self):
        for prefix in ('utf8','utf8mb3'):
            for suffix in ('general_ci','unicode_ci','unicode_520_ci','bin','turkish_ci','vietnamese_ci'):
                with self.subTest(prefix=prefix,suffix=suffix):
                    sql='DECLARE v VARCHAR(10) CHARACTER SET '+prefix+' COLLATE '+prefix+'_'+suffix+';'
                    expected='DECLARE v VARCHAR(10) CHARACTER SET utf8mb4 COLLATE utf8mb4_'+suffix+';'
                    self.assertEqual(transform(sql),expected)
                    self.assertEqual(transform(expected),expected)

    def test_unknown_utf8_collation_requires_mapping(self):
        for suffix in ('general_mysql500_ci','tolower_ci','custom_ci'):
            sql='DECLARE v VARCHAR(10) CHARSET utf8 COLLATE utf8_'+suffix+';'
            with self.assertRaisesRegex(ValueError,'No verified utf8mb4 equivalent'):
                transform(sql)

    def test_existing_charset_comments_are_kept(self):
        sql="DECLARE v VARCHAR(10) /*CHARSET utf8*/ DEFAULT ''; DECLARE w TEXT /*CHARSET utf8mb4*/;"
        self.assertEqual(transform(sql),sql)

    def test_user_utf8_declaration_examples(self):
        sql='''DECLARE payBill VARCHAR(10) charset utf8;
DECLARE eventType,resultType,specVal,userLang, ReplStr VARCHAR(16) charset utf8;
DECLARE gameName VARCHAR(255) charset utf8 DEFAULT '';
DECLARE msgOutText, descript VARCHAR(1000) charset utf8 DEFAULT '';'''
        expected=sql.replace('charset utf8','charset utf8mb4')
        self.assertEqual(transform(sql),expected)
        self.assertEqual(transform(expected),expected)

    def test_utf8_variants_and_collations(self):
        for charset in ('utf8','utf8mb3','utf8mb4','UTF8'):
            for keyword in ('charset','CHARSET =','CHARACTER SET','CHARACTER SET ='):
                with self.subTest(charset=charset,keyword=keyword):
                    clause=keyword+' '+charset
                    sql='DECLARE v VARCHAR(10) '+clause+' COLLATE '+charset+'_general_ci DEFAULT \'x\';'
                    expected=('DECLARE v VARCHAR(10) '+keyword+' utf8mb4 COLLATE utf8mb4_general_ci DEFAULT \'x\';')
                    self.assertEqual(transform(sql),expected)
        for charset in ('latin1','utf8mb40','utf8mb3_extra'):
            sql='DECLARE v VARCHAR(10) CHARACTER SET '+charset+';'
            self.assertEqual(transform(sql),sql)

    def test_utf8_clause_comments_and_literals(self):
        sql='''DECLARE a VARCHAR(10) /*charset utf8*/ DEFAULT 'charset utf8';
DECLARE b VARCHAR(20) CHARACTER /*note*/ SET utf8 COLLATE /*note2*/ utf8_general_ci;
DECLARE c TEXT CHARACTER -- note3
SET utf8;
-- DECLARE d TEXT charset utf8;
SET @x='DECLARE d TEXT charset utf8';'''
        result=transform(sql)
        self.assertIn("/*charset utf8*/ DEFAULT 'charset utf8'",result)
        self.assertIn('CHARACTER /*note*/ SET utf8mb4 COLLATE /*note2*/ utf8mb4_general_ci',result)
        self.assertIn('CHARACTER -- note3\nSET utf8mb4',result)
        self.assertIn('-- DECLARE d TEXT charset utf8;',result)
        self.assertIn("'DECLARE d TEXT charset utf8'",result)
        self.assertNotIn('/*/*',result)
        self.assertEqual(transform(result),result)

    def test_utf8_parameters_and_return_type(self):
        sql='''CREATE DEFINER=`u`@`%` FUNCTION db.f(v VARCHAR(10) charset utf8, n DECIMAL(10,2), e ENUM('a,b','c') CHARACTER SET utf8mb4)
RETURNS VARCHAR(20) CHARACTER SET utf8 COLLATE utf8_general_ci
DETERMINISTIC BEGIN DECLARE x TEXT charset utf8; RETURN v; END;'''
        expected=sql.replace('charset utf8','charset utf8mb4').replace('CHARACTER SET utf8 ','CHARACTER SET utf8mb4 ').replace('COLLATE utf8_general_ci','COLLATE utf8mb4_general_ci')
        self.assertEqual(transform(sql),expected)
        sql='CREATE PROCEDURE p(IN a VARCHAR(10) charset utf8, OUT b CHAR(1) charset utf8mb4, INOUT c TEXT charset utf8mb3) BEGIN SET b=a; END;'
        expected=sql.replace('charset utf8,','charset utf8mb4,').replace('charset utf8mb3)','charset utf8mb4)')
        self.assertEqual(transform(sql),expected)

    def test_utf8_runtime_expressions_and_table_definitions(self):
        sql='''DECLARE v VARCHAR(10) charset utf8 DEFAULT 'a' COLLATE utf8_bin;
SELECT x COLLATE utf8_bin FROM t;
CREATE TEMPORARY TABLE t(x VARCHAR(10) charset utf8) DEFAULT CHARSET=utf8;
SET NAMES utf8mb4 COLLATE utf8mb4_general_ci;'''
        expected=sql.replace('DECLARE v VARCHAR(10) charset utf8','DECLARE v VARCHAR(10) charset utf8mb4').replace('t(x VARCHAR(10) charset utf8) DEFAULT CHARSET=utf8','t(x VARCHAR(10) charset utf8mb4) DEFAULT CHARSET=utf8mb4')
        self.assertEqual(transform(sql),expected)

    def test_utf8_quoted_names_and_type_names(self):
        sql='DECLARE a CHARACTER(10) CHARACTER SET \'utf8\' COLLATE `utf8_general_ci`; DECLARE b NATIONAL CHAR(1) CHARSET="utf8mb4";'
        expected=sql.replace("CHARACTER SET 'utf8'","CHARACTER SET 'utf8mb4'").replace('COLLATE `utf8_general_ci`','COLLATE `utf8mb4_general_ci`')
        self.assertEqual(transform(sql),expected)

    def test_utf8_same_line_and_handler_combination(self):
        sql='''BEGIN DECLARE errNom INT; DECLARE errText VARCHAR(100) charset utf8;
DECLARE keepMe VARCHAR(10) charset utf8;DECLARE alsoKeep TEXT charset utf8;
DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN GET DIAGNOSTICS CONDITION 1 errNom=MYSQL_ERRNO,errText=MESSAGE_TEXT;END;END'''
        result=transform(sql)
        self.assertNotIn('DECLARE errText',result)
        self.assertIn('DECLARE keepMe VARCHAR(10) charset utf8mb4;DECLARE alsoKeep TEXT charset utf8mb4;',result)
        self.assertIn('@errNom=MYSQL_ERRNO,@errText=MESSAGE_TEXT',result)
        self.assertEqual(transform(result),result)

    def test_utf8_conversion_option(self):
        old=os.environ.get('CONVERT_UTF8_TO_UTF8MB4')
        try:
            os.environ['CONVERT_UTF8_TO_UTF8MB4']='0'
            sql='DECLARE a VARCHAR(10) charset utf8;'
            self.assertEqual(transform(sql),sql)
        finally:
            if old is None:
                os.environ.pop('CONVERT_UTF8_TO_UTF8MB4',None)
            else:
                os.environ['CONVERT_UTF8_TO_UTF8MB4']=old

    def test_original_handler(self):
        sql = '''CREATE PROCEDURE p() BEGIN
DECLARE errNom INT UNSIGNED DEFAULT 0;
DECLARE errText VARCHAR(100);
DECLARE rowNo INT DEFAULT 0;
DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
 GET DIAGNOSTICS CONDITION 1 errNom=MYSQL_ERRNO,errText=MESSAGE_TEXT;
 INSERT IGNORE INTO tools.error_log(err_no,err_text,row_no) VALUES(errNom,errText,rowNo);
END;
END'''
        result = transform(sql)
        self.assertNotIn('DECLARE errNom',result)
        self.assertNotIn('DECLARE errText',result)
        self.assertIn('DECLARE rowNo INT DEFAULT 0;',result)
        self.assertIn('@errNom=MYSQL_ERRNO,@errText=MESSAGE_TEXT',result)
        self.assertIn('VALUES(@errNom,@errText,rowNo)',result)
        self.assertEqual(transform(result),result)

    def test_shared_declarations_permutations(self):
        for length in range(2,6):
            for names in itertools.permutations(['errNom','errText','rowNo','other','third'],length):
                if not {'errNom','errText'} & set(names):
                    continue
                with self.subTest(names=names):
                    sql = ('BEGIN DECLARE '+','.join(names)+' INT DEFAULT 0;'
                           'DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN '
                           'GET DIAGNOSTICS CONDITION 1 errNom=MYSQL_ERRNO,errText=MESSAGE_TEXT; END; END')
                    result = transform(sql)
                    remaining=[n.lower() for n in names if n not in ('errNom','errText')]
                    tokens=words(result)
                    if remaining:
                        index=tokens.index('declare')
                        self.assertEqual(tokens[index+1:tokens.index('int')],
                                         [v for j,n in enumerate(remaining) for v in ([',',n] if j else [n])])
                    else:
                        self.assertNotIn('int',tokens)
                    self.assertEqual(transform(result),result)

    def test_other_statement_on_same_line(self):
        sql='BEGIN DECLARE errNom INT;DECLARE keepMe INT;DECLARE EXIT HANDLER FOR SQLEXCEPTION SET errNom=1; END'
        result=transform(sql)
        self.assertIn('DECLARE keepMe INT;',result)
        self.assertIn('SET @errNom=1',result)

    def test_nested_binding_and_outside_reference(self):
        sql='''BEGIN DECLARE errNom INT; DECLARE EXIT HANDLER FOR SQLEXCEPTION SET errNom=1;
SET errNom=0; BEGIN DECLARE errNom INT; SET errNom=2; END; END'''
        result=transform(sql)
        self.assertIn('SET @errNom=0',result)
        self.assertIn('BEGIN DECLARE errNom INT; SET errNom=2;',result)

    def test_strings_comments_columns(self):
        sql='''BEGIN DECLARE errNom INT;DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
-- DECLARE errNom INT; over REGEXP BINARY
SET errNom=1; SET @s='errNom over REGEXP BINARY';
/* errText over REGEXP BINARY */
INSERT INTO log(errNom) VALUES(errNom);
SELECT t.errNom AS errNom FROM t;
END; END'''
        result=transform(sql)
        self.assertIn("'errNom over REGEXP BINARY'",result)
        self.assertIn('-- DECLARE errNom INT; over REGEXP BINARY',result)
        self.assertIn('/* errText over REGEXP BINARY */',result)
        self.assertIn('INSERT INTO log(errNom) VALUES(@errNom)',result)
        self.assertIn('SELECT t.errNom AS errNom',result)

    def test_no_handler_unchanged(self):
        sql='BEGIN DECLARE errNom INT; SET errNom=1; END'
        self.assertEqual(transform(sql),sql)

    def test_update_column_targets(self):
        sql='''BEGIN DECLARE errNom INT;DECLARE EXIT HANDLER FOR SQLEXCEPTION BEGIN
SET errNom=1; UPDATE log SET errNom=errNom,other=COALESCE(errNom,0) WHERE id=1;
INSERT INTO log(errNom) VALUES(errNom) ON DUPLICATE KEY UPDATE errNom=errNom;
END; END'''
        result=transform(sql)
        self.assertIn('SET @errNom=1;',result)
        self.assertIn('UPDATE log SET errNom=@errNom,other=COALESCE(@errNom,0)',result)
        self.assertIn('ON DUPLICATE KEY UPDATE errNom=@errNom;',result)

    def test_table_names_followed_by_parenthesis(self):
        sql='CREATE TEMPORARY TABLE groups(id INT); INSERT INTO groups(id) VALUES(1);'
        self.assertEqual(transform(sql),'CREATE TEMPORARY TABLE `groups`(id INT); INSERT INTO `groups`(id) VALUES(1);')

    def test_existing_session_and_case(self):
        sql='BEGIN DECLARE ERRNOM INT; DECLARE EXIT HANDLER FOR SQLEXCEPTION SET @errNom=1; END'
        result=transform(sql)
        self.assertNotIn('DECLARE ERRNOM',result)
        self.assertNotIn('@@errNom',result)

    def test_handler_conditions(self):
        for condition in ["SQLSTATE '45000'", "SQLSTATE VALUE '45000', 1234", 'NOT FOUND', 'SQLWARNING, SQLEXCEPTION', 'custom_error']:
            sql='BEGIN DECLARE errNom INT; DECLARE CONTINUE HANDLER FOR '+condition+' BEGIN IF 1 THEN SET errNom=1; END IF; CASE 1 WHEN 1 THEN SET errNom=2; END CASE; END; END'
            self.assertNotIn('DECLARE errNom',transform(sql))

    def test_reserved_words(self):
        sql='SELECT over INTO v FROM t WHERE over<=3 ORDER BY over; DECLARE groups INT; SET groups=1;'
        result=transform(sql)
        self.assertEqual(result,'SELECT `over` INTO v FROM t WHERE `over`<=3 ORDER BY `over`; DECLARE `groups` INT; SET `groups`=1;')
        self.assertEqual(transform(result),result)

    def test_real_window_and_recursive_syntax(self):
        sql='WITH RECURSIVE c AS (SELECT 1) SELECT RANK() OVER (ORDER BY x), ROW_NUMBER() OVER w FROM t WINDOW w AS (ORDER BY y);'
        self.assertEqual(transform(sql),sql)

    def test_regexp(self):
        sql="SELECT x REGEXP BINARY 'A', y regexp /*note*/ binary 'B', z REGEXP `BINARY`; -- REGEXP BINARY\n"
        result=transform(sql)
        self.assertIn("x REGEXP  'A'",result)
        self.assertIn("y regexp /*note*/  'B'",result)
        self.assertIn('z REGEXP `BINARY`',result)
        self.assertTrue(result.endswith('-- REGEXP BINARY\n'))

    def test_offline_cli_atomic_failure(self):
        import tempfile
        folder=tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        p=Path(folder.name)/'invalid.sql'
        p.write_text("SELECT 'unterminated")
        result=subprocess.run(['bash',str(SCRIPT),'--transform',str(p)],capture_output=True)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(p.read_text(),"SELECT 'unterminated")

if __name__=='__main__':
    unittest.main(verbosity=2)
