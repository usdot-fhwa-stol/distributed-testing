#!/bin/bash 

set -euo pipefail

print_help() {
	printf "\nusage: fix_non-static_db.sh [-d <directory>] [-f <database file>] \n"

	printf "\nUpdate TENA sqlite databases that will not export in dataview\n"

	printf "\noptional arguments:\n"
	printf "\t -f <database file> , \t --file <database file> \t input database file to be decoded\n"
	printf "\t -d <directory> , \t --directory <directory> \t directory to search for database files\n"
	printf "\t -h, --help \t\t\t\t\t\t show help\n"
}

# database_file="NONE"

next_flag_is_database_file=false
next_flag_is_directory=false
database_file=""
directory=""


for arg in "$@"
do
	if [ "$next_flag_is_database_file" = true ]; then

		database_file=$arg
		next_flag_is_database_file=false

	elif [ "$next_flag_is_directory" = true ]; then

		directory=$arg
		next_flag_is_directory=false

	elif [[ $arg == "-d" ]] || [[ $arg == "--directory" ]]; then
		
		next_flag_is_directory=true
	
	elif [[ $arg == "-f" ]] || [[ $arg == "--file" ]]; then
		
		next_flag_is_database_file=true

	elif [[ $arg == "--help" ]] || [[ $arg == "-h" ]]; then
		
		print_help
		exit

	elif [[ $arg != "" ]]; then
		
		printf "\nInvalid argument: $arg\n"
		print_help
		exit

	fi
done

# Function to check StopTime value in the first row of CollectionData table
check_stop_time() {
	local sqlite_file=$1
	# Check if CollectionData table exists
	table_exists=$(sqlite3 "$sqlite_file" "SELECT name FROM sqlite_master WHERE type='table' AND name='CollectionData';")
	if [[ $table_exists == "CollectionData" ]]; then
		# Fetch the first StopTime value from the CollectionData table
		stop_time=$(sqlite3 "$sqlite_file" "SELECT StopTime FROM CollectionData LIMIT 1;")

		printf "\tStopTime: $stop_time\n"
		if [[ $stop_time == "0" ]]; then
			printf "\tStopTime is zero\n"
			update_stop_time "$sqlite_file"
		else
			printf "\tStopTime is non-zero\n"
		fi
	else
		printf "\tTable CollectionData does not exist in file: $sqlite_file\n"
	fi
}

update_stop_time(){


new_stop_time_value=1

# Run the SQLite query to update the StopTime value
sqlite3 "$1" <<EOF
UPDATE CollectionData
SET StopTime = $new_stop_time_value
WHERE rowid = 1;
EOF

new_stop_time=$(sqlite3 "$1" "SELECT StopTime FROM CollectionData LIMIT 1;")

if [[ $new_stop_time == "0" ]]; then
	printf "\tERROR: StopTime not updated\n"
else
	printf "\tStopTime successfully updated\n"
fi


}

# if [[ $database_file == "NONE" ]]; then
# 	printf
# 	printf "Please specificy a database file\n"
# 	print_help
# 	exit
# fi

if [ -z "$directory" ] && [ -z "$database_file" ]; then
	printf "\nNeither file (-f) nor directory (-d) set. Please set one of these arguments.\n"
	print_help
	exit
fi

if [ -n "$directory" ] && [ -n "$database_file" ]; then
	printf "\nFile (-f) and directory (-d) both set. Please set only one of these arguments.\n"
	print_help
	exit
fi

printf "database_file: %s\n" "$database_file"
printf "directory: %s\n" "$directory"

# Ensure mysql-client is installed
REQUIRED_PKG="sqlite3"
PKG_OK=$(dpkg-query -W --showformat='${Status}\n' $REQUIRED_PKG|grep "install ok installed")
printf Checking for $REQUIRED_PKG: $PKG_OK
if [ "" = "$PKG_OK" ]; then
  printf "No $REQUIRED_PKG found. Installing $REQUIRED_PKG.\n"
  sudo apt-get update
  sudo apt-get --yes install $REQUIRED_PKG
fi

if [ -n "$directory" ]; then

	printf "Directory found: $directory\n"

	# Find all SQLite files in the given directory and subdirectories
	find "$directory" -type f -name "*.sqlite" | while read -r sqlite_file; do

		printf "Checking $sqlite_file\n"

		check_stop_time "$sqlite_file"
	done

fi

if [ -n "$database_file" ]; then
	
	printf "Database file found: $database_file\n"

	update_stop_time "$database_file"

	printf "\nDatabase updated successfully.\n"
fi