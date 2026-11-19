import mysql.connector
from mysql.connector import Error
import constants
import pandas as pd 
import sys 

#Attempts to establish connection to the mysql server running on the host_name param.
#Additional parameters required are the login credentials for the mysql server.
def create_server_connection(host_name, user_name, user_password):
    connection = None
    try:
        connection = mysql.connector.connect(
            host=host_name,
            user=user_name,
            passwd=user_password
        )
        print("MySQL Database connection successful \n")
    except Error as err:
        print(f"Error: '{err}'")

    return connection

#Attempts to execute the input query and prints success/error message.
def execute_query(connection, query):
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        print("Query successful \n")
    except Error as err:
        print(f"Error: '{err}'")

#Read results from a select query and returns the result in "result" variable
def read_query(connection, query):
    cursor = connection.cursor()
    result = None
    try:
        cursor.execute(query)
        result = cursor.fetchall()
        return result
    except Error as err:
        print(f"Error: '{err}'")

#Sets the pluginConfigurationParameter v2xhub database with the values in the input file 
def pluginSetValues(fileName):
    #read in user list of desired database changes and store the plugins in a list
    plugins = pd.read_csv(fileName)
    pluginsList = plugins['pluginName'].unique()

    #get the user's v2xhub database configuration and store in a dictionary
    join_query = "SELECT a.pluginId, a.key, a.value, b.exeName FROM " + constants.DATABASE_NAME + "." + constants.PLUGIN_CONFIGURATION_TABLE \
    + " a LEFT JOIN " + constants.DATABASE_NAME + "." + constants.PLUGIN_NAME_TABLE + " b ON a.pluginId = b.pluginId"
    print(join_query)
    join_results = read_query(connection, join_query)
    pluginIdDict = {}

    for result in join_results:
        try:
            pluginId = result[0]
            pluginName = result[3].split("/bin/")[1]
            pluginIdDict[pluginId] = pluginName
        except:
            continue

    #iterate through list of desired plugins to update and use the dictionary created above to update the appropriate entries
    for plugin in pluginsList:
        #create a subset of the data containing individual plugin changes
        subset = plugins[plugins['pluginName'] == plugin]
        name = subset['pluginName'].iloc[0]
        user_id = str({i for i in pluginIdDict if pluginIdDict[i]==name}).replace("{","").replace("}","")

        #iterate through each row in the data and create sql UPDATE query
        for index,row in subset.iterrows():
            update_query = "UPDATE " + constants.DATABASE_NAME + "." + constants.PLUGIN_CONFIGURATION_TABLE + " SET value='" + row[2] + "' WHERE `key`='" + row[1] + "'" \
            + " AND pluginId='" + str(user_id) + "';"
            print(update_query + "\n")
            execute_query(connection, update_query)

        #verify values have been properly updated
        select_query = "SELECT * FROM " + constants.DATABASE_NAME + "." + constants.PLUGIN_CONFIGURATION_TABLE + " WHERE pluginId='" + str(user_id) + "';"
        print("Current values in the database for " + str(name) + ": \n")
        results = read_query(connection, select_query)

        for result in results:
            print(result)    

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Pass the name of database values file: "python3 v2xhub_sql.py <filename>"')
    else:
        #Read in name of database values file
        values_file = sys.argv[1]

        #Setup connection to the mysql server
        connection = create_server_connection("127.0.0.1", constants.SQL_SERVER_USERNAME, constants.SQL_SERVER_PW)

        #Set the desired values in the IVP pluginConfigurationParameter database
        pluginSetValues(values_file)