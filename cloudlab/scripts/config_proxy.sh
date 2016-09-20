#! /bin/bash

sudo apt-get update > /dev/null 2>&1
sudo apt-get install -y sshpass python-setuptools vim curl > /dev/null 2>&1
sudo apt-get install software-properties-common -y > /dev/null 2>&1
sudo add-apt-repository ppa:webupd8team/java -y > /dev/null 2>&1
sudo apt-get update > /dev/null 2>&1
sudo easy_install networkx > /dev/null 2>&1

sshpass -p "passwd" scp -o StrictHostKeyChecking=no -r user@public-ip:~/src-proxy/ . > /dev/null 2>&1
