#! /usr/bin/python

import subprocess
import sys
import json

ssh_host_file = '../conf/ssh_host'
ssh_hosts_raw = []
hosts = []

with open(ssh_host_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_hosts_raw.append(ret)

l = len(ssh_hosts_raw)

for i in range(0, l):
    print 'host %d' % i
    ret = ssh_hosts_raw[i]
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo route -en > route_info" % (ret[2], ret[3]), shell=True)
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ip route del 10.0.0.0/8" % (ret[2], ret[3]), shell=True)
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ip route add 10.0.0.0/8 dev eth1" % (ret[2], ret[3]), shell=True)
    ip = subprocess.check_output("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ifconfig eth1 2>/dev/null|awk '/inet addr:/ {print $2}'|sed 's/addr://'" % (ret[2], ret[3]), shell=True)
    mac = subprocess.check_output("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo cat /sys/class/net/eth1/address" % (ret[2], ret[3]), shell=True)
    ip = ip[0: len(ip)-1]
    mac = mac[0: len(mac)-1]
    hosts.append([ip, mac])


for i in range(0, l):
    print 'host %d' % i
    ret = ssh_hosts_raw[i]
    for ip, mac in hosts:
        subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo arp -s %s %s -i eth1" % (ret[2], ret[3], ip, mac), shell=True)
