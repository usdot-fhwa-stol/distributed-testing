import sqlite3
import argparse
import sys
import shutil
import os
import traceback

def find_matching_rows(database_file, ip_address, entity_type, is_msg):
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(database_file)
        cursor = conn.cursor()
        
        # Find the table with the required name pattern ending with "const"
        if is_msg:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{entity_type}%'")

            


            table_name_with_const = cursor.fetchone()

            if not table_name_with_const:
                print(f"\tNo table found for {entity_type}.")
                return []
            
            table_name_with_const = table_name_with_const[0]

            if not table_name_with_const:
                print(f"\tNo matching table found for {entity_type}.")
                return []
            
            # # Find the table with the same name but without "const" at the end
            # #       For msg, there is no const so table with and without will be the same
            table_name_without_const = table_name_with_const

            # Query the table and get matching rowIDs
            query = f'SELECT rowID, "Metadata,Endpoint" FROM "{table_name_with_const}"'
            cursor.execute(query)
            rows = cursor.fetchall()


            final_matching_row_ids = []
            for row in rows:
                row_id, metadata_endpoint = row
                endpoint = metadata_endpoint.split(',')[-1]
                endpoint_ip = endpoint.split(':')[0]
                if endpoint_ip == ip_address:
                    final_matching_row_ids.append(row_id)

            print(f'\tFound {len(final_matching_row_ids)} rows matching IP')

        else:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{entity_type}%const'")

            table_name_with_const = cursor.fetchone()
            table_name_with_const = table_name_with_const[0]

            print(f"\tFound const table: {table_name_with_const}")

            if not table_name_with_const:
                print(f"\tNo matching table found for {entity_type}.")
                return []

            # Find the table with the same name but without "const" at the end
            #       For msg, there is no const so table with and without will be the same
            table_name_without_const = table_name_with_const.replace(",const", "")
        
            # Query the table and compare IP addresses
            query = f'SELECT rowID, "Metadata,Endpoint" FROM "{table_name_with_const}"'
            cursor.execute(query)
            rows = cursor.fetchall()

            matching_row_ids = []
            for row in rows:
                row_id, metadata_endpoint = row
                endpoint = metadata_endpoint.split(',')[-1]
                endpoint_ip = endpoint.split(':')[0]
                # print(f'\t\t{endpoint_ip} : {ip_address}')
                if endpoint_ip == ip_address:
                    matching_row_ids.append(row_id)

            # If no matching rows are found, return early
            if not matching_row_ids:
                print(f"No matching rows found for {entity_type}.")
                return []
            else:
                print(f'\tFound {len(matching_row_ids)} matching IPs in const table')

            # Construct the column name
            column_name = f'DB,{table_name_with_const},rowID'
            

            # Query the second table and get matching rowIDs
            query = f'SELECT rowID, "{column_name}" FROM "{table_name_without_const}"'
            cursor.execute(query)
            rows = cursor.fetchall()

            final_matching_row_ids = []
            for row in rows:
                row_id, reference_row_id = row
                if reference_row_id in matching_row_ids:
                    final_matching_row_ids.append(row_id)

            print(f'\tFound {len(final_matching_row_ids)} rows matching IP')

        # Close the connection
        conn.close()

        return final_matching_row_ids

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        sys.exit(1)
    except Exception:
        print(traceback.format_exc())
        sys.exit(1)

def delete_rows(database_file, entity_type, row_ids, is_msg, include_rows=True):
    try:
        # Connect to the SQLite database
        conn = sqlite3.connect(database_file)
        cursor = conn.cursor()

        # Find the table with the required name pattern ending with "const"
        if is_msg:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{entity_type}%'")
        else:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '{entity_type}%const'")

        table_name = cursor.fetchone()

        if not table_name:
            print(f"Table for {entity_type} not found, not deleting rows")
            return

        # Find the table with the same name but without "const" at the end
        table_name_without_const = table_name[0].replace(",const", "")

        # Query the table and compare IP addresses
        query = f'SELECT rowID, "Metadata,Endpoint" FROM "{table_name_without_const}"'
        cursor.execute(query)


        if include_rows:
            # Delete all rows that are not in the matching row IDs
            query = f'DELETE FROM "{table_name_without_const}" WHERE rowID NOT IN ({",".join(map(str, row_ids))})'
        else:
            # Delete all rows that are in the matching row IDs
            query = f'DELETE FROM "{table_name_without_const}" WHERE rowID IN ({",".join(map(str, row_ids))})'

        cursor.execute(query)
        conn.commit()

        # Close the connection
        conn.close()

    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
        sys.exit(1)
    except Exception:
        print(traceback.format_exc())
        sys.exit(1)


def create_folder(directory_path,directory_name_list,force_split):
    
    delete_old_data = None
    confirmation = None

    for directory_name in directory_name_list:
        
        exported_folder_path = os.path.join(directory_path, directory_name)
        # Check if the folder already exists and there are files in it
        if os.path.exists(exported_folder_path) and len([file for file in os.listdir(directory_path) if os.path.isfile(os.path.join(directory_path, file))]) > 0:
            # Confirm with the user before deleting
            
            if force_split == True:
                delete_old_data = True
                break

            elif force_split == False:
                delete_old_data = False
                print("\tKeeping old data.")
                
            else:
                confirmation = input(f"\nExsisting {directory_name} data found, delete old data and re-export? [y/n]: ").lower()
                if confirmation == 'y':
                    delete_old_data = True
                    break
                else:
                    delete_old_data = False
                    print("\tKeeping old data.")
            
    # if we confrirmed, delete the data
    if delete_old_data:
        try:
            for directory_name in directory_name_list:
                exported_folder_path = os.path.join(directory_path, directory_name)
                # Use shutil.rmtree to delete the folder and its contents
                shutil.rmtree(exported_folder_path)
                print(f"\tFolder '{exported_folder_path}' deleted successfully.")

        except Exception as e:
            print(f"\tError deleting folder: {e}")
            sys.exit()

        except Exception:
            print(f'tError deleting folder: \n{traceback.format_exc()}')
            sys.exit(1)
    # if we said no to deletting data, keep the data and move on
    elif delete_old_data == False:
        return True
    
    # if we did not get the confirmation or we deleted them, create them
    for directory_name in directory_name_list:
        exported_folder_path = os.path.join(directory_path, directory_name)
        try:
            os.makedirs(exported_folder_path)
            print(f"\tCreated {directory_name} folder in {directory_path}")
        except OSError as e:
            print(f"\tError creating folder {exported_folder_path}: {e}")

def split_tdcs(database_file,ip_address,force_split):

    database_file_directory = os.path.dirname(database_file)
    database_file_basename = os.path.basename(database_file)

    database_file_prefix, file_extension = os.path.splitext(database_file_basename)
    outbound_database_file = f"{database_file_prefix}_outbound{file_extension}"
    inbound_database_file = f"{database_file_prefix}_inbound{file_extension}"

    skip_export = create_folder(database_file_directory,["split_tdcs"],force_split)

    outbound_database_file_full = os.path.join(database_file_directory,"split_tdcs",outbound_database_file)
    inbound_database_file_full = os.path.join(database_file_directory,"split_tdcs",inbound_database_file)

    if skip_export == True:
        return
    #entity_types = ["Class,VUG::Entities::Vehicle","Class,VUG::Entities::Signals::TrafficLight","Msg,VUG::TJ2735Msg::J2735","Msg,VUG::TJ3224Msg::J3224","Class,VUG::Track::BSM"]
    entity_types = ["Class,DOT_OSTR::Entities::LandVehicle","Class,DOT_OSTR::Entities::TrafficSignalController","Msg,DOT_OSTR::TV2XMsg::V2X"]
    matching_rows_by_type = {}

    for entity_type in entity_types:
        print(f"Finding matching rows for {ip_address} in {entity_type}")
        if entity_type.startswith("Msg,"):
            is_msg = True
        else:
            is_msg = False

        matching_row_ids = find_matching_rows(database_file, ip_address, entity_type,is_msg)

        # print(f'matching_row_ids for {entity_type}: {matching_row_ids}')

        # if matching_row_ids:
        matching_rows_by_type[entity_type] = matching_row_ids
            # print(f'\tMatching Rows: {matching_row_ids}')

    # all_matching_row_ids = set(vehicle_matching_row_ids + traffic_light_matching_row_ids)

    if matching_rows_by_type:
        # Copy the original database to the new database files
        print(f"Creating outbound database copy: {outbound_database_file_full}")
        shutil.copyfile(database_file, outbound_database_file_full)
        print(f"Creating inbound database copy: {inbound_database_file_full}")
        shutil.copyfile(database_file, inbound_database_file_full)

        # Delete rows from the copied databases
        for entity_type in matching_rows_by_type:
            if entity_type.startswith("Msg,"):
                is_msg = True
            else:
                is_msg = False
            delete_rows(outbound_database_file_full, entity_type, matching_rows_by_type[entity_type], is_msg, include_rows=True)
            delete_rows(inbound_database_file_full, entity_type, matching_rows_by_type[entity_type], is_msg, include_rows=False)
        print("Databases created successfully.")
    else:
        print("No matching rows found in any tables.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Find matching rows in a SQLite database based on IP address and create two new databases.')
    parser.add_argument('-f', '--database_file', type=str, required=False, help='Location of the SQLite database file')
    parser.add_argument('-i', '--ip_address', type=str, required=True, help='IP address to match')

    args = parser.parse_args()

    split_tdcs(args.database_file,args.ip_address)


