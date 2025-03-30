USE tools;
DROP PROCEDURE IF EXISTS `tools`.`gen_schemes_script`;
DELIMITER $$

CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `gen_schemes_script`(IN SchemeName VARCHAR(64))
    COMMENT 'Create backup of all procedure every 2 days'
ExitSub:BEGIN
	DECLARE errNom INT DEFAULT 0;
   DECLARE errText VARCHAR(255) DEFAULT '';
	-- call tools.gen_schemes_script('bets'); -- Get specific Scheme
	-- call tools.gen_schemes_script('');     -- Get all schemas

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
			GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
			SELECT errNom, errText;
		END;
		  
	SELECT CONCAT('CREATE DATABASE IF NOT EXISTS \`',SCHEMA_NAME,'\` CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;') FROM information_schema.SCHEMATA WHERE
	SCHEMA_NAME NOT IN('information_schema','performance_schema','mysql','ndbinfo')
		 AND SCHEMA_NAME = IF(SchemeName<>'', SchemeName, SCHEMA_NAME);
END $$ 
DELIMITER ;