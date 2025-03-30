#!/bin/bash

# Define MySQL credentials
MYSQL_USER="dev"
MYSQL_HOST="10.18.0.72"
MYSQL_PORT="3306"

# Prompt for the password without showing it
echo -n "Enter MySQL password: "
read -s MYSQL_PASS
echo

# Define output files
PROC_FILE="proc.sql"
TEMP_CMD_FILE="commands.sh"

# Display menu options
echo "Choose an option:"
echo "1. Create all stored procedures and functions from all databases"
echo "2. Create only one specific stored procedure or function"
echo "3. Create all stored procedures and functions from a specific database"
read -p "Enter your choice (1/2/3): " choice

# Define SQL query based on the choice
SQL_QUERY=""

case $choice in
    1)
        # Option 1: Create all stored procedures and functions from all databases
	ALL_PROC_FILE="${MYSQL_HOST}_all_proc.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASS -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $PROC_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $PROC_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $PROC_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $PROC_FILE\n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $PROC_FILE && sed -i \"/DECLARE errNom', CHAR(92), '|DECLARE errText/d\" $PROC_FILE \n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $PROC_FILE && sed -i \"0,/BEGIN/ { /BEGIN/ a\\ ', CHAR(92),CHAR(92),CHAR(92), 'tDECLARE errNom INT DEFAULT 0;', CHAR(92),'n   DECLARE errText VARCHAR(255) DEFAULT ', CHAR(39), CHAR(39),';\\n}\" $PROC_FILE \n',
            'cat $PROC_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a ORDER BY a.ROUTINE_SCHEMA, a.ROUTINE_NAME;"
        ;;
    2)
        # Option 2: Create only one specific stored procedure or function
        read -p "Enter the routine name: " ROUTINE_NAME
	read -p "Enter the database name: " DB_NAME
	OUTPUT_FILE="proc.sql" # Define custom output file based on host id, DB and routine name
	ALL_PROC_FILE="${MYSQL_HOST}_${DB_NAME}.${ROUTINE_NAME}.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASS -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $OUTPUT_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $OUTPUT_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $OUTPUT_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $OUTPUT_FILE\n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $OUTPUT_FILE && sed -i \"/DECLARE errNom', CHAR(92), '|DECLARE errText/d\" $OUTPUT_FILE \n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $OUTPUT_FILE && sed -i \"0,/BEGIN/ { /BEGIN/ a\\ ', CHAR(92),CHAR(92),CHAR(92), 'tDECLARE errNom INT DEFAULT 0;', CHAR(92),'n   DECLARE errText VARCHAR(255) DEFAULT ', CHAR(39), CHAR(39),';\\n}\" $OUTPUT_FILE \n',
            'cat $OUTPUT_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a 
        WHERE a.ROUTINE_NAME = '$ROUTINE_NAME' AND a.ROUTINE_SCHEMA = '$DB_NAME'
        LIMIT 1;"
        ;;
    3)
        # Option 3: Create all stored procedures and functions from a specific database
        read -p "Enter the database name: " DB_NAME
        OUTPUT_FILE="${DB_NAME}.sql" # Define custom output file based on DB name
        ALL_PROC_FILE="${MYSQL_HOST}_${DB_NAME}.sql"
        SQL_QUERY="
        SELECT CONCAT(
            'mysql -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASS -e \"SHOW CREATE ', a.ROUTINE_TYPE, ' ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92),'\\\`.', CHAR(92),'\\\`', a.ROUTINE_NAME, CHAR(92),'\\\`\" --silent --raw --skip-column-names > $OUTPUT_FILE\n',
            'sed -i \"0,/CREATE DEFINER=/s/.*CREATE DEFINER=/CREATE DEFINER=/\" $OUTPUT_FILE\n',
            'sed -i \"1i\\USE ', CHAR(92),'\\\`', a.ROUTINE_SCHEMA, CHAR(92), '\\\`;', CHAR(92), 'nDROP ', a.ROUTINE_TYPE, ' IF EXISTS ', CHAR(92), '\\\`', a.ROUTINE_NAME, CHAR(92), '\\\`;',CHAR(92),'ndelimiter ;;\" $OUTPUT_FILE\n',
            'sed -E -i \'s/', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+', CHAR(92), 't[a-zA-Z0-9_]+$//; ',char(36),'s/$/', CHAR(92), 'n;;', CHAR(92), 'ndelimiter ;/\' $OUTPUT_FILE\n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $OUTPUT_FILE && sed -i \"/DECLARE errNom', CHAR(92), '|DECLARE errText/d\" $OUTPUT_FILE \n',
            'grep -q \"GET DIAGNOSTICS CONDITION\" $OUTPUT_FILE && sed -i \"0,/BEGIN/ { /BEGIN/ a\\ ', CHAR(92),CHAR(92),CHAR(92), 'tDECLARE errNom INT DEFAULT 0;', CHAR(92),'n   DECLARE errText VARCHAR(255) DEFAULT ', CHAR(39), CHAR(39),';\\n}\" $OUTPUT_FILE \n',
            'cat $OUTPUT_FILE >> $ALL_PROC_FILE \n'
        ) AS all_proc
        FROM information_schema.ROUTINES a 
        WHERE a.ROUTINE_SCHEMA = '$DB_NAME'
        ORDER BY a.ROUTINE_NAME;"
        ;;
    *)
        echo "Invalid choice!"
        exit 1
        ;;
esac

# Execute the query and write commands to the temporary file
mysql -P $MYSQL_PORT -h $MYSQL_HOST -u $MYSQL_USER -p$MYSQL_PASS -e "$SQL_QUERY" --silent --raw --skip-column-names > $TEMP_CMD_FILE

# Uncomment the following line to execute the commands after verifying their correctness
bash $TEMP_CMD_FILE

# Clean up temporary command file
rm -f $TEMP_CMD_FILE

rm -f $PROC_FILE

rm -f $OUTPUT_FILE

