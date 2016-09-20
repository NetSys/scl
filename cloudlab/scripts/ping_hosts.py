#! /usr/bin/python

import subprocess
import json

ssh_host_file = '../conf/ssh_host'
host_file = '../conf/fattree_outband_cloudlab.json'
ssh_hosts_raw = []
hosts_ip = []

def byteify(input):
    '''
    convert unicode from json.loads to utf-8
    '''
    if isinstance(input, dict):
        return {byteify(key): byteify(value) for key, value in input.iteritems()}
    elif isinstance(input, list):
        return [byteify(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input

with open(host_file) as f:
    topo = byteify(json.load(f))
    for host in topo['hosts'].keys():
        hosts_ip.append(topo['hosts'][host])

with open(ssh_host_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_hosts_raw.append(ret)

l = len(ssh_hosts_raw)

for i in range(0, l):
    print 'host %d' % i
    ret = ssh_hosts_raw[i]
    for j in range(0, l):
        print 'dst: %s' % hosts_ip[j]
        subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ping %s -c 1" % (ret[2], ret[3], hosts_ip[j]), shell=True)
