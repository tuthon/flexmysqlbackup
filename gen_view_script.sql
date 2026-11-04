USE tools;
DROP PROCEDURE IF EXISTS `tools`.`gen_view_script`;
DELIMITER $$

CREATE DEFINER=`Sup_User_SPESA`@`%` PROCEDURE `tools`.`gen_view_script`(IN tableschema VARCHAR(64), IN ViewName VARCHAR(64))
ExitSub:BEGIN
-- call tools.gen_view_script('', '');                        -- Backup all views from all schemas
-- call tools.gen_view_script('database name', '');           -- Backup all views for particular schema
-- call tools.gen_view_script('database name', 'view name');  -- Backup for only particular view
    DECLARE errNom, RowNo INT DEFAULT 0;
    DECLARE errText VARCHAR(255) DEFAULT '';

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        GET DIAGNOSTICS CONDITION 1 errText = MESSAGE_TEXT, errNom = MYSQL_ERRNO;
        SELECT RowNo, errNom, errText, tableschema, ViewName;
    END;

    SET RowNo = 2;
    SELECT CONCAT(
        -- USE: unqualified functions in VIEW_DEFINITION are resolved in the view's own schema
        'USE `', TABLE_SCHEMA, '`;\n',
        'DROP VIEW IF EXISTS `', TABLE_SCHEMA, '`.`', TABLE_NAME, '`;\n',
        'CREATE OR REPLACE',
        -- DEFINER is 'user@host'; split on the LAST '@' (host part can never contain '@')
        ' DEFINER=`', LEFT(DEFINER, CHAR_LENGTH(DEFINER) - CHAR_LENGTH(SUBSTRING_INDEX(DEFINER, '@', -1)) - 1),
        '`@`', SUBSTRING_INDEX(DEFINER, '@', -1), '`',
        ' SQL SECURITY ', SECURITY_TYPE,
        ' VIEW `', TABLE_SCHEMA, '`.`', TABLE_NAME, '` AS ', VIEW_DEFINITION,
        IF(CHECK_OPTION = 'NONE', '', CONCAT(' WITH ', CHECK_OPTION, ' CHECK OPTION')),
        ';\n'
    ) AS fullscript
    FROM information_schema.VIEWS
    WHERE TABLE_SCHEMA NOT IN ('mysql', 'information_schema', 'performance_schema', 'ndbinfo', 'ndbmemcache', 'sys')
      AND (tableschema = '' OR TABLE_SCHEMA = tableschema)
      AND (ViewName    = '' OR TABLE_NAME   = ViewName);

END $$
DELIMITER ;
