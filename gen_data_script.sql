DROP PROCEDURE IF EXISTS  `tools`.`gen_data_script`;

delimiter $$
CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `tools`.`gen_data_script`(IN SchemeName VARCHAR(64), in tableName VARCHAR(1000), in EngineName varchar(64))  ExitSub:BEGIN
-- CALL tools.gen_data_script('SchemeName', tableName, EngineName);
-- CALL tools.gen_data_script('', '', ''); -- All tables
-- CALL tools.gen_data_script('SchemeName', '', ''); -- All tables for particular schema
-- CALL tools.gen_data_script('SchemeName', 'tableName', ''); -- Only for particular table
-- CALL tools.gen_data_script('', '', 'EngineName'); -- Only for particular engine
-- CALL tools.gen_data_script('SchemeName', '', 'EngineName'); -- Only for particular engine and schema

	DECLARE errNom INT DEFAULT 0;
	DECLARE errText, MysqlVer VARCHAR(255) DEFAULT '';

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
			GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
			SELECT errNom, errText;
		END;

SET MysqlVer = VERSION();

SET SESSION group_concat_max_len = 50000;
SELECT
	CONCAT( 'mysqldump -P 3306 -hlocalhost -udba -pdba --no-create-db --no-create-info', IF(LEFT(MysqlVer, 2) = '5.', '', ' --column-statistics=0'), ' --skip-triggers --extended-insert --default-character-set=utf8mb4 --no-tablespaces --databases ',
	TABLE_SCHEMA, ' ', IF(tableName<>'', REPLACE ( GROUP_CONCAT( TABLE_NAME ), ',', ' ' ), ' ' ), ' > backup_', @@hostname, '_', TABLE_SCHEMA, '_data.sql' ) as data_gen_script
FROM information_schema.`TABLES` 
WHERE	`ENGINE` = IF(EngineName='', `ENGINE`, EngineName) 
		 AND TABLE_SCHEMA NOT IN ( 'information_schema', 'performance_schema', 'mysql', 'ndbinfo', '_development', '_test') 
		 AND TABLE_SCHEMA = IF(SchemeName='', TABLE_SCHEMA, SchemeName)
		 AND TABLE_NAME   = IF(tableName='', TABLE_NAME, tableName) 
GROUP BY	TABLE_SCHEMA ORDER BY TABLE_SCHEMA, TABLE_NAME;

END$$
delimiter ;
