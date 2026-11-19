The first script “v2xhub_sql_import.py” will attempt to create a connection to the mysql server running and will save pertinent information related to the installed plugins, their configuration parameters, and current settings. It will save this data to a csv called “current_configuration.csv”.

The second python script “v2xhub_sql_update.py” can be used to update plugin configuration parameters. The user should make a csv file with the desired plugin configuration parameters and pass it to this script. To do this, simply update the “current_configuration.csv” to only contain entries for the plugins you are interested in updating, along with the corresponding updated fields.

Once you run the update script, you will see the values changed on the V2X Hub web UI. It shouldn’t matter if the plugin is currently enabled or disabled. 
