USE tools;
DROP PROCEDURE IF EXISTS `tools`.`gen_view_script`;
DELIMITER $$

CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `gen_view_script`(in tableschema VARCHAR(64), in ViewName VARCHAR(64))
ExitSub:BEGIN
-- call tools.gen_view_script('', ''); -- Backup all views from all schemas
-- call tools.gen_view_script('database name', ''); -- Backup all views for particular schema
-- call tools.gen_view_script('database name', 'view name'); -- Backup for only particular view
	DECLARE errNom, RowNo INT DEFAULT 0;
   DECLARE errText VARCHAR(255) DEFAULT '';

	DECLARE EXIT HANDLER FOR SQLEXCEPTION
		BEGIN
      GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT ,errNom = MYSQL_ERRNO;
		SELECT RowNo, errNom, errText, tableschema, ViewName;
		END;

	SET @@group_concat_max_len = 30000000;
	
	IF tableschema='' AND ViewName='' THEN -- Create all VIEWS script
		SET RowNo=2;
		SELECT CONCAT("DROP VIEW IF EXISTS ", TABLE_SCHEMA, ".", TABLE_NAME, ";\nCREATE OR REPLACE VIEW ", TABLE_SCHEMA, ".", TABLE_NAME, " AS ", VIEW_DEFINITION, ";\n") as fullscript 
		FROM information_schema.views where TABLE_SCHEMA NOT IN("mysql", "information_schema", "performance_schema", "ndbinfo", "ndbmemcache", "sys");
	ELSEIF tableschema<>'' AND ViewName='' THEN -- Create all views from particular schema
		SET RowNo=4;
		SELECT CONCAT("DROP VIEW IF EXISTS ", TABLE_SCHEMA, ".", TABLE_NAME, ";\nCREATE OR REPLACE VIEW ", TABLE_SCHEMA, ".", TABLE_NAME, " AS ", VIEW_DEFINITION, ";\n") as fullscript  
		FROM information_schema.views where TABLE_SCHEMA = tableschema AND TABLE_SCHEMA NOT IN("mysql", "information_schema", "performance_schema", "ndbinfo", "ndbmemcache", "sys");		
	ELSE  -- Create only for particular VIEW script
		SET RowNo=6;
		SELECT CONCAT("DROP VIEW IF EXISTS ", TABLE_SCHEMA, ".", TABLE_NAME, ";\nCREATE OR REPLACE VIEW ", TABLE_SCHEMA, ".", TABLE_NAME, " AS ", VIEW_DEFINITION, ";\n") as fullscript  
		FROM information_schema.views where TABLE_SCHEMA = tableschema AND TABLE_NAME = ViewName AND TABLE_SCHEMA NOT IN("mysql", "information_schema", "performance_schema", "ndbinfo", "ndbmemcache", "sys");		
	
	END IF;

END $$ 
DELIMITER ;

