#! /bin/bash

sudo apt-get update > /dev/null 2>&1
sudo apt-get -y install sshpass vim > /dev/null 2>&1

sshpass -p "passwd" scp -o StrictHostKeyChecking=no -r user@public-ip:~/src-agent/ . > /dev/null 2>&1

ip a > ip_info
cd ~/src-agent/openvswitch/ > /dev/null 2>&1
sudo ./setup_openvswitch.sh > /dev/null 2>&1
sudo ./start_openvswitch.sh > /dev/null 2>&1
