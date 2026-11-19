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

#import current configuration values and save to csv
def importConfigurationValues():
    join_query = "SELECT a.pluginId, a.key, a.value, b.exeName FROM " + constants.DATABASE_NAME + "." + constants.PLUGIN_CONFIGURATION_TABLE \
    + " a LEFT JOIN " + constants.DATABASE_NAME + "." + constants.PLUGIN_NAME_TABLE + " b ON a.pluginId = b.pluginId"
    join_results = read_query(connection, join_query)
    df = pd.DataFrame(join_results)
    df.columns=["pluginId", "key", "value", "pluginName"]
    df.to_csv("current_configuration.csv", index=False)


if __name__ == '__main__':
    #Setup connection to the mysql server and import config values
    connection = create_server_connection("127.0.0.1", "root", "ivp")
    importConfigurationValues()
