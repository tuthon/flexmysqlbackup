DROP PROCEDURE IF EXISTS  `tools`.`gen_triggers_script`;

delimiter $$
CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `gen_triggers_script`(IN SchemeName VARCHAR(64) CHARACTER SET utf8 COLLATE utf8_general_ci, IN TrigName VARCHAR(64))
ExitSub:BEGIN
	DECLARE errNom INT DEFAULT 0;
   DECLARE errText VARCHAR(255) DEFAULT '';
	-- call tools.gen_triggers_script('kannel', 'before_insert_inbox_kanel'); -- Only a specific trigger
	-- call tools.gen_triggers_script('kannel', ''); -- Triggers by schema
	-- call tools.gen_triggers_script('', ''); -- All triggers
	DECLARE RowNo INT DEFAULT 0;
	DECLARE FullScript LONGTEXT CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';
	DECLARE BySchemaNameCon, ByTrigNameCon VARCHAR(100) CHARACTER SET utf8 COLLATE utf8_general_ci DEFAULT '';

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
      GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
				SELECT RowNo, errNom, errText;
		END;

	SET SESSION sql_mode="NO_ENGINE_SUBSTITUTION";
	
	IF SchemaName <> '' AND TrigName <> '' THEN -- Only a specific trigger 
		SET BySchemaNameCon = CONCAT("where	TRIGGER_SCHEMA='", SchemaName, "'");
		SET ByTrigNameCon = CONCAT(" AND TRIGGER_NAME='", TrigName, "' limit 1;");
	ELSEIF SchemaName <> '' AND TrigName = '' THEN -- Triggers by schema
		SET @@group_concat_max_len = 1000000;
		SET BySchemaNameCon = CONCAT("where	TRIGGER_SCHEMA='", SchemaName, "' ORDER BY TRIGGER_NAME;");
	ELSE
		SET @@group_concat_max_len = 1000000;
		SET ByTrigNameCon = 'ORDER BY TRIGGER_SCHEMA, TRIGGER_NAME;'; -- All triggers
	END IF;		

	SET @SqlSt=CONCAT("SELECT GROUP_CONCAT(CONCAT('DROP TRIGGER IF EXISTS ', ' `', TRIGGER_SCHEMA, '`.`', `TRIGGER_NAME`, '`', ';\ndelimiter $$\nCREATE DEFINER=`Sup_User_SPESA`@`%` TRIGGER `', TRIGGER_SCHEMA, '`.`', `TRIGGER_NAME`,'` ', ACTION_TIMING, ' ', EVENT_MANIPULATION, ' ON `', EVENT_OBJECT_SCHEMA, '`.`', EVENT_OBJECT_TABLE,
			'` FOR EACH ', ACTION_ORIENTATION, ' ', ACTION_STATEMENT, '\n$$\ndelimiter ;') SEPARATOR '\n\n') as FullScript
				FROM information_schema.`TRIGGERS` ", BySchemaNameCon, ByTrigNameCon);
-- SELECT @SqlSt;
	SET rowNo=8; PREPARE stmt FROM @SqlSt; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$
delimiter ;