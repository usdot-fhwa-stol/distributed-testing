## Build TENA Adapter Script
The buildTenaAdapters.sh automates the build process for TENA adapters which require a build container. Currently the script can be used to build the following adapters: 

 - Carla Adapter
 - TENA V2X Gateway
 - TENA SPaT Plugin

## Prerequisites

 - The following packages are installed:
	 - build-essentials
 - The following TENA packages are installed on the local machine in $HOME/TENA:
	- TENA-MiddlewareSDK-v6.0.8.B@Product@u2004-gcc9-64-va0b09d44.bin
	- TENA-boost-v1.77.0.1@Product@u2004-gcc9-64-vall.bin
	- VUG-VOICES-Combined-Distribution-v0.12.0@Product@u2004-gcc9-64-v1976e608.bin
 - All prerequisite bin packages including the TENA Middleware are downloaded and placed in a single directory.
	 - Prerequisite packages for each adapter can be found on its BitBucket page at www.trmc.osd.mil/bitbucket

## Instructions

 1. Modify the LOCAL VARIABLES and TENA VARIABLES in buildTenaAdapters.sh to match your system. 
 2. Execute the script: `./buildTenaAdapters`
 3. Enter the index number of the adapter you would like to build.
 4. If an application git directory is not found in the `localInstallDir`, you will be prompted to download the latest version from git*.
 5. If installing the an adapter that is a V2X Plugin (TENA V2X Gateway and TENA SPaT Plugin) and a V2X Hub git directory is not found in the `localInstallDir`, you will be prompted to download the latest version from git.
 6. If an existing build docker container for the desired build exists, you will be prompted whether you would like to rebuild the build container.
 7. If an existing build folder is found, you will be prompted to regenerate the make files. NOTE: If you enter Yes, the entire build folder will be deleted and recreated.


\* Due to current DOD restrictions, TENA source code is hosted on a private TRMC repository. For access, please contact the TRMC for account creation and the VOICES team for repository access. 


