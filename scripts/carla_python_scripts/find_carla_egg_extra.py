import glob
import os
import sys

import importlib.util
import subprocess
import re

import fnmatch
from os.path import expanduser

def find_file(pattern, path):
    result = []
    for root, dirs, files in os.walk(path):
        for name in files:
            if fnmatch.fnmatch(name, pattern):
                result.append(os.path.join(root, name))
    return result 

def find_element_from_key_value(dict_to_search,search_key,search_value):
    for element in dict_to_search:
        if fnmatch.fnmatch(search_value,element.search_key):
            return element

need_to_install_import = True

try:
        
    package = importlib.util.find_spec('carla')
    found = package is not None

    #print("CARLA Package found: " + str(package.origin))

    package_egg_dir_search = re.search("^.*egg",str(package.origin))
    package_egg_dir = package_egg_dir_search.group()
    print("package_egg_dir: " + str(package_egg_dir))

    package_egg_search = re.search("carla.*egg",str(package_egg_dir))
    package_egg = package_egg_search.group()
    print("package_egg: " + str(package_egg))

    dist_package_dir_search = re.search("^.*dist-packages",str(package.origin))
    dist_package_dir = dist_package_dir_search.group()
    easy_install_pth = dist_package_dir + "/easy-install.pth"
    print("easy_install_pth: " + str(easy_install_pth))

    print("")
    reinstall = input("Would you like to remove and reinstall/import the carla egg? [y/n]  ")

    yes_choices = ['yes', 'y']
    no_choices = ['no', 'n']

    if reinstall.lower() in yes_choices:
        rm_egg_bashCommand = "sudo rm -rf " + package_egg_dir
        rm_egg_process = subprocess.Popen(rm_egg_bashCommand.split(), stdout=subprocess.PIPE)
        rm_egg_output, rm_egg_error = rm_egg_process.communicate()

        sed_egg_bashCommand = "sed -i '/" + package_egg + "/d' " + easy_install_pth
        print("bashCommand: " + sed_egg_bashCommand)
        sed_egg_process = subprocess.Popen(sed_egg_bashCommand.split(), stdout=subprocess.PIPE)
        output, error = sed_egg_process.communicate()

        need_to_install_import = True
        
    else:
        need_to_install_import = False
        sys.exit()


except Exception as err_msg:
    print(str(err_msg))
    print("")
    print("Unable to import carla, attempting to find carla egg file")

if need_to_install_import:
    #this looks for the carla python API .egg file in ~/
    try:
        print("")

        carla_egg_name = 'carla-0.9.15*' + str(sys.version_info.major) + '*-' + str('win-amd64' if os.name == 'nt' else 'linux-x86_64') + '.egg'
        print("Looking for CARLA egg: " + carla_egg_name)
        carla_egg_locations = find_file(carla_egg_name,expanduser("~"))
        #print("Found carla egg(s): " + str(carla_egg_locations))

        if len(carla_egg_locations) == 1:
            carla_egg_to_use = carla_egg_locations[0]
        else:
            print("\nFound multiple carla egg files: ")
            for i,egg_found in enumerate(carla_egg_locations):
                print("[" + str(i+1) + "]    " + egg_found)

            egg_selected = input("\nSelect a carla egg file to use: ")

            try:
                egg_selected = int(egg_selected)
            except:
                print("\nInvalid selection, please try again")
                sys.exit()

            if (egg_selected <= len(carla_egg_locations)):
                carla_egg_to_use = carla_egg_locations[egg_selected-1]
            else:
                print("\nInvalid selection, please try again")
                sys.exit()

        print("")
        print("Would you like to install or import the found egg?")
        print("    install - add to python as a package (will not need to import again)")
        print("    import - import egg for this script execution (will need to import for every script execution)")

        valid_response = False
        while not valid_response:
            import_install = input("\n[import/install]: ")

            if import_install == "import":
                sys.path.append(carla_egg_to_use)
                valid_response = True
            elif import_install == "install":

                bashCommand = "sudo python3 -m easy_install " + carla_egg_to_use
                process = subprocess.Popen(bashCommand.split(), stdout=subprocess.PIPE)
                output, error = process.communicate()
                valid_response = True
            else:
                print("Invalid selection, try again")

    except Exception as err_msg:
        print(str(err_msg))
        print("\nFailed to install carla egg")

        

import carla