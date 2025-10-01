#! /bin/bash

source /home/carla/start_scripts/setup-carla-docker.sh

if [[ $VUG_DOCKER_START_CARLA == 'local' ]]; then
   echo "STARTING CARLA DOCKER"
elif [[ $VUG_DOCKER_START_CARLA == 'remote' ]]; then
   echo "USING REMOTE CARLA, CARLA DOCKER NOT STARTING"
   exit 1
elif [[ $VUG_DOCKER_START_CARLA == 'off' ]]; then
   echo "CARLA SET TO OFF, CARLA DOCKER NOT STARTING"
   exit 1
else
   echo "UNKNOWN VUG_DOCKER_START_CARLA VALUE: $VUG_DOCKER_START_CARLA, CARLA DOCKER NOT STARTING"
   echo "    VALID VUG_DOCKER_START_CARLA VALUES: local, remote, off"
   exit 1
fi

carla_graphics_api_arg=""

if [[ $VUG_CARLA_GRAPHICS_API == "vulkan" ]]; then
   echo "SETTING CARLA GRAPHICS API TO VULKAN"
   carla_graphics_api_arg="-vulkan"

elif [[ $VUG_CARLA_GRAPHICS_API == "opengl" ]]; then
   echo "SETTING CARLA GRAPHICS API TO OPENGL"
   carla_graphics_api_arg="-opengl"
fi

carla_graphics_quality_arg=""

if [[ $VUG_CARLA_QUALITY_LEVEL == "Epic" ]]; then
   echo "CARLA GRAPHICS QUALITY SET TO EPIC"
   carla_graphics_quality_arg="-quality-level=Epic"

elif [[ $VUG_CARLA_QUALITY_LEVEL == "Low" ]]; then
   echo "CARLA GRAPHICS QUALITY SET TO LOW"
   carla_graphics_quality_arg="-quality-level=Low"
fi

# adding this somehow prevents a carla memory crash: https://github.com/carla-simulator/carla/issues/2138
vulkaninfo &> /dev/null

echo "STARTING CARLA"


if [[ $VUG_CARLA_MAP_NAME == "TFHRC" ]]; then
   CARLA_LOCATION="/home/CARLA_TFHRC"
else
   CARLA_LOCATION="/home/carla"
fi


/bin/bash $CARLA_LOCATION/CarlaUE4.sh $carla_graphics_api_arg $carla_graphics_quality_arg -nosound &

sleep 5s

echo "VUG CARLA STARTUP COMLPETE"

tail -f /dev/null