DROP PROCEDURE IF EXISTS  `tools`.`gen_table_script`;

delimiter $$
CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `tools`.`gen_table_script`(IN act int, in tableschema VARCHAR(64), in tableName VARCHAR(64), in EngineName varchar(64), in CharacterName VARCHAR(64), IN CollationNam VARCHAR(64) )  ExitSub:BEGIN
-- call tools.gen_table_script(1, '', '', '', '', ''); -- Backup all tables from all schemas
-- call tools.gen_table_script(1, 'database name', '', '', '', ''); -- Backup all tables for particular schema
-- call tools.gen_table_script(1, '', '', 'engine name', '', ''); -- Backup all tables for for related engine
-- call tools.gen_table_script(1, 'database name', '', 'engine name', '', ''); -- Backup for particular schema and only for related engine
-- call tools.gen_table_script(1, 'database name', 'table name', '', '', ''); -- Backup for only particular table
-- call tools.gen_table_script(1, '', '', '', 'add character set', 'add collation'); -- change all columns option and table option to use defined "CHARACTER SET" and "COLLATION". This option can be add for all actions
	DECLARE errNom, RowNo INT DEFAULT 0;
   DECLARE errText VARCHAR(255) DEFAULT '';
	DECLARE TableType, `TabEngine`, ColumnName, DataType, NameSchema, NameTable, LastTable, LastSchema VARCHAR(64) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE PrimaryKeyDef VARCHAR(200) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE TableCollation VARCHAR(32) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE EngineParam VARCHAR(32) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT NULL;
	DECLARE RowFormat VARCHAR(10) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE TableComment, IndexDef, ForeignKey VARCHAR(2048) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE SchemaNames VARCHAR(21845) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE TablesNames text CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE TablesScript longtext CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE AllColumn MEDIUMTEXT CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
      GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
		SELECT RowNo, errNom, errText, NameSchema, TablesNames, NameTable, TablesScript, @createtable;
		END;

	SET @@group_concat_max_len = 30000000;

	IF act= 1 THEN -- BY ENGINE or ALL
	
		IF tableschema<>'' AND TableName<>'' THEN -- Get only particular table
			SET RowNo=2;
			SELECT TABLE_TYPE, `ENGINE`, ROW_FORMAT, TABLE_COLLATION, TABLE_COMMENT INTO TableType, `TabEngine`, RowFormat, TableCollation, TableComment
				FROM information_schema.`TABLES` WHERE TABLE_SCHEMA=TableSchema AND TABLE_NAME=TableName AND TABLE_SCHEMA NOT IN('mysql', 'information_schema', 'performance_schema', 'ndbinfo', 'ndbmemcache', 'sys') LIMIT 1;	

			SET NameSchema=TableSchema, NameTable=TableName;

			IF TableName IS NULL THEN
				SELECT 'info' as res, 'Not exists table!' as description; LEAVE ExitSub;
			END IF;
		ELSE -- Get by Schema and or Engine
			SET @TablesNames=NULL;
			IF EngineName <> '' THEN
				SET EngineParam = CONCAT(' AND `ENGINE` = "', EngineName, '";');
			ELSE
				SET EngineParam = ';';
			END IF;
			
			SET RowNo=4;
			IF tableschema<>'' THEN
				SELECT SCHEMA_NAME INTO SchemaNames FROM information_schema.`SCHEMATA` WHERE SCHEMA_NAME=tableschema AND SCHEMA_NAME NOT IN('mysql', 'information_schema', 'performance_schema', 'ndbinfo', 'ndbmemcache', 'sys');
			ELSE
				SELECT GROUP_CONCAT(SCHEMA_NAME) INTO SchemaNames FROM information_schema.`SCHEMATA` WHERE SCHEMA_NAME NOT IN('mysql', 'information_schema', 'performance_schema', 'ndbinfo', 'ndbmemcache', 'sys');
			END IF;
			
			IF SchemaNames IS NULL THEN SELECT 'info' as res, 'Not exists SCHEMA!' as description; LEAVE ExitSub; END IF;
		END IF;

		ExitL:LOOP
			IF TableName='' THEN -- Get by Schema and or Engine
				SET RowNo=6;
				SET NameSchema=SUBSTRING_INDEX(SchemaNames,',',1);
				IF NameSchema=LastSchema THEN /*SELECT 73, TablesScript, NameSchema, LastSchema, 'info' as res, 'Last Schema!' as description;*/ LEAVE ExitL; END IF;
				SET LastSchema=NameSchema;
				SET SchemaNames=TRIM(LEADING CONCAT(NameSchema, ',') FROM SchemaNames);

				SET @SqlSt=CONCAT('SELECT GROUP_CONCAT(TABLE_NAME) INTO @TablesNames FROM information_schema.`TABLES` WHERE TABLE_SCHEMA="', NameSchema, '" AND TABLE_TYPE<>"VIEW"', EngineParam);

				SET rowNo=8; PREPARE stmt FROM @SqlSt; EXECUTE stmt; DEALLOCATE PREPARE stmt;
	-- SELECT 1, @SqlSt, @TablesNames; LEAVE ExitSub;			
				IF @TablesNames IS NULL THEN /*SELECT 79, 'info' as res, 'Not exists Tables!' as description, NameSchema, SchemaNames, @TablesNames;*/ ITERATE ExitL; END IF;
			END IF;
-- 			SET @cnt=0;
			ExitL2:LOOP
				IF TableName='' THEN
					SET NameTable=SUBSTRING_INDEX(@TablesNames, ',', 1);
					SET RowNo=10;
					IF LastTable=NameTable THEN /*SELECT 83, NameSchema, SchemaNames, @TablesNames, LastTable, NameTable;*/ LEAVE ExitL2; END IF;
					
					SET LastTable=NameTable;
					SET @TablesNames=TRIM(LEADING CONCAT(NameTable, ',') FROM @TablesNames);
					SET RowNo=12;
					SET TableType='', `TabEngine`='', RowFormat='', TableCollation='', TableComment='';
					SELECT TABLE_TYPE, `ENGINE`, ROW_FORMAT, TABLE_COLLATION, TABLE_COMMENT INTO TableType, `TabEngine`, RowFormat, TableCollation, TableComment
						FROM information_schema.`TABLES` WHERE TABLE_SCHEMA=NameSchema AND TABLE_NAME=NameTable LIMIT 1;	
				END IF;

				SET TableComment=REPLACE(TableComment, "'", "");
				SET RowNo=14;				
				SET @createtable='', AllColumn='', PrimaryKeyDef='', IndexDef='';

				SELECT REPLACE(GROUP_CONCAT(
				  CONCAT(IF(COLUMN_TYPE='geometry', '\n', '\n`'), 
							IF(COLUMN_TYPE='geometry', CONCAT('/*!50705 `', COLUMN_NAME), COLUMN_NAME), 
							'` ', 
							IF(COLUMN_TYPE='geometry', CONCAT(COLUMN_TYPE, ' */ /*!80003 SRID 0 */ /*!50705 '), COLUMN_TYPE),
							IF(CHARACTER_SET_NAME IS NOT NULL,  IF(CharacterName<>'', CONCAT(' CHARACTER SET ', CharacterName, ' '), CONCAT(' CHARACTER SET ', CHARACTER_SET_NAME, ' ') ), ''), 
							IF(COLLATION_NAME IS NOT NULL, IF(CollationNam<>'', CONCAT(' COLLATE ', CollationNam, ' '), CONCAT(' COLLATE ', COLLATION_NAME, ' ')), ''), 		
							IF(IS_NULLABLE='NO', ' NOT NULL ', ' NULL '),
							IF(COLUMN_DEFAULT IS NULL, '',  CONCAT(' DEFAULT ', IF(COLUMN_DEFAULT='', "''", IF(COLUMN_DEFAULT='CURRENT_TIMESTAMP ', CONCAT(COLUMN_DEFAULT, " "), CONCAT("'", REPLACE(COLUMN_DEFAULT, "'", "''"), "'"))      ))),
							-- IF(EXTRA<>'' AND EXTRA <> 'DEFAULT_GENERATED', CONCAT(' ', EXTRA, ' '), ''),
							REPLACE(EXTRA, 'DEFAULT_GENERATED', ''),
										IF(COLUMN_COMMENT<>'', CONCAT(' COMMENT \'', REPLACE(COLUMN_COMMENT, "'", ""), '\' '), ''), IF(COLUMN_TYPE='geometry', ',*/,,,&*YG^&', '')) ORDER BY ORDINAL_POSITION
							), ',,,&*YG^&,', '' ) INTO AllColumn
				FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = NameSchema AND TABLE_NAME = NameTable ORDER BY ORDINAL_POSITION;

				SET RowNo=18;
				SELECT IFNULL(CONCAT('\nPRIMARY KEY (', GROUP_CONCAT('`', COLUMN_NAME, '`' ORDER BY SEQ_IN_INDEX),')', IF(INDEX_TYPE='BTREE', ' USING BTREE,', ',')), '') INTO PrimaryKeyDef FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=NameSchema AND TABLE_NAME = NameTable AND INDEX_NAME='PRIMARY';	
				SET RowNo=20;
				SELECT IFNULL(REPLACE(GROUP_CONCAT(t1.Def), '*/,', '*/'), '') INTO IndexDef FROM
				(SELECT CONCAT(IF(NON_UNIQUE=0, '\nUNIQUE KEY `', IF(INDEX_TYPE = 'SPATIAL', '\n/*!50705 SPATIAL KEY `',  IF(INDEX_TYPE = 'FULLTEXT', '\nFULLTEXT KEY `', '\nKEY `'))),				
										INDEX_NAME, 
										'` (', 
										GROUP_CONCAT('`', COLUMN_NAME, '`', IF(SUB_PART IS NOT NULL AND INDEX_TYPE <> 'SPATIAL', CONCAT('(', SUB_PART, ')'), '') ORDER BY SEQ_IN_INDEX),
										')', 
										IF(INDEX_TYPE = 'SPATIAL', ',*/', ''),
										IF(INDEX_TYPE='BTREE', ' USING BTREE', '')
								  ) as Def 
					FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=NameSchema AND TABLE_NAME = NameTable AND INDEX_NAME<>'PRIMARY' GROUP BY INDEX_NAME) as t1; 

				IF IndexDef='' THEN SET PrimaryKeyDef=TRIM(TRAILING ',' FROM PrimaryKeyDef); END IF;
					
				IF PrimaryKeyDef<>'' OR IndexDef<>'' THEN SET AllColumn=CONCAT(AllColumn, ','); END IF;
				
				-- GET FOREIGN KEY
				SELECT IFNULL(GROUP_CONCAT(t1.Foreign_Key), '') INTO ForeignKey FROM
				(SELECT CONCAT('\nCONSTRAINT `', RefCons.CONSTRAINT_NAME, '` FOREIGN KEY (`', KeyCol.COLUMN_NAME, '`) REFERENCES `', RefCons.REFERENCED_TABLE_NAME, '` (`', KeyCol.REFERENCED_COLUMN_NAME, '`)' 
				, IF(RefCons.DELETE_RULE<>'NONE', CONCAT(' ON DELETE ', RefCons.DELETE_RULE), ' '), IF(RefCons.UPDATE_RULE<>'NONE', CONCAT(' ON UPDATE ', RefCons.UPDATE_RULE), ' ') ) as Foreign_Key
				FROM information_schema.referential_constraints RefCons
				JOIN information_schema.key_column_usage KeyCol ON RefCons.constraint_schema = KeyCol.table_schema
				-- LEFT JOIN information_schema.INNODB_SYS_FOREIGN -- -- 0 = ON DELETE/UPDATE RESTRICT, 1 = ON DELETE CASCADE, 2 = ON DELETE SET NULL, 4 = ON UPDATE CASCADE, 8 = ON UPDATE SET NULL, 16 = ON DELETE NO ACTION, 32 = ON UPDATE NO ACTION.
					  AND RefCons.table_name = KeyCol.table_name
					  AND RefCons.constraint_name = KeyCol.constraint_name
						WHERE RefCons.constraint_schema=NameSchema AND RefCons.TABLE_NAME=NameTable) as t1;

				SET RowNo=22;
-- 				SET @createtable=CONCAT('USE `', NameSchema, '`;\nCREATE TABLE IF NOT EXISTS `', NameSchema, '`.`', NameTable,'` (', AllColumn, PrimaryKeyDef, IF(ForeignKey<>'', CONCAT(IndexDef, ','), IndexDef), ForeignKey, '\n)ENGINE = ', TabEngine,
					SET @createtable=CONCAT('USE `', NameSchema, '`;\nCREATE TABLE IF NOT EXISTS `', NameSchema, '`.`', NameTable,'` (', AllColumn, PrimaryKeyDef, IF(ForeignKey<>'', IF(SUBSTRING_INDEX(IndexDef, ',', -1)= '*/', IndexDef, CONCAT(IndexDef, ',')), IndexDef), ForeignKey, '\n)ENGINE = ', TabEngine,
												' CHARACTER SET = ', IF(CharacterName<>'', CharacterName, SUBSTRING_INDEX(TableCollation,'_',1) ), ' COLLATE = ', IF(CollationNam<>'', CollationNam , TableCollation), ' ROW_FORMAT = ', RowFormat,
												IF(TableComment<>'', CONCAT(' COMMENT \'', TableComment, '\' '), ''), ';\n\n');			
				
				IF TableName<>'' THEN -- If condition has only one particular table
					SELECT @createtable; Leave ExitSub;
				END IF;							
												
				SET RowNo=24;
				SET TablesScript=CONCAT(TablesScript, @createtable);
				IF TablesScript IS NULL THEN /*SELECT 139, TablesScript, @createtable, NameSchema, NameTable, AllColumn, PrimaryKeyDef, IndexDef, TabEngine;*/ LEAVE ExitSub; END IF;
-- 				SET @cnt=@cnt+1; IF @cnt>=200 THEN SELECT 123,  NameSchema, SchemaNames, @TablesNames, LastTable, NameTable; LEAVE ExitSub; END IF;
			END LOOP;
		END LOOP;
		
		SELECT CONCAT("SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0;\nSET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0;\nSET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='TRADITIONAL';\n", TablesScript) as TablesScript;
	END IF;
	
	IF act= 5 THEN -- Create VIEWS script
		SET RowNo=26;
		SELECT CONCAT("DROP VIEW IF EXISTS ", TABLE_SCHEMA, ".", TABLE_NAME, ";\nCREATE OR REPLACE VIEW ", TABLE_SCHEMA, ".", TABLE_NAME, " AS ", VIEW_DEFINITION, ";\n") table_name 
		FROM information_schema.views where TABLE_SCHEMA NOT IN("mysql", "information_schema", "performance_schema", "ndbinfo", "ndbmemcache", "sys");
	END IF;

END$$
delimiter ;