USE tools;
DROP PROCEDURE IF EXISTS `tools`.`gen_event_script`;
DELIMITER $$

CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `gen_event_script`(IN SchemaName VARCHAR(64), IN EventName VARCHAR(64))
    COMMENT 'Create backup of all procedure every 2 days'
ExitSub:BEGIN
	DECLARE errNom INT DEFAULT 0;
   DECLARE errText VARCHAR(255) DEFAULT '';
	-- call tools.gen_event_script('bets', 'bets_settle'); -- Get only specific event
	-- call tools.gen_event_script('bets', 			  ''); -- Get all events for specific schema
	-- call tools.gen_event_script(''	 , 			  ''); -- Get all events for all schemas

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
			GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
			SELECT errNom, errText;
		END;	

	SET SESSION sql_mode="NO_ENGINE_SUBSTITUTION";
	SET @@group_concat_max_len = 20000000;
		  
	SELECT GROUP_CONCAT(
					 CONCAT(
								'DROP EVENT IF EXISTS ', ' `', EVENT_SCHEMA, '`.`', EVENT_NAME, '`', ';\n',
								'delimiter $$ \nCREATE DEFINER=`Sup_User_SPESA`@`%` EVENT `', EVENT_SCHEMA, '`.`', EVENT_NAME, 
								'` ON SCHEDULE EVERY ', INTERVAL_VALUE, ' ', INTERVAL_FIELD, 
								' STARTS \'', STARTS, '\' ',
								'ON COMPLETION ', REPLACE(ON_COMPLETION, 'DROP', 'NOT PRESERVE'), ' ', 
								REPLACE(REPLACE(STATUS, 'DISABLED', 'DISABLE'), 'ENABLED', 'ENABLE'), 
								' COMMENT "',
								REPLACE(REPLACE(EVENT_COMMENT, '"', '\\"'), "'", "\\'"),
								'" ',
								'DO ', EVENT_DEFINITION, ';$$\n',
							   'delimiter ;'
							) ORDER BY EVENT_SCHEMA, EVENT_NAME
					  SEPARATOR '\n\n'
							) as events_script
		 FROM information_schema.EVENTS 
		 WHERE EVENT_SCHEMA = IF(SchemaName<>'', SchemaName, EVENT_SCHEMA) AND EVENT_NAME = IF(EventName<>'', EventName, EVENT_NAME);
END $$ 
DELIMITER ;