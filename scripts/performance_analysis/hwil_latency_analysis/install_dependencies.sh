#!/bin/sh

set -e
sudo apt-get update 

# Install pcap decoder tool
git clone https://github.com/usdot-fhwa-stol/pcapdecoder.git
cd pcapdecoder/install
# Install python and j2735_202409 packages
./install_dependencies.sh

