#! /usr/bin/python

import json
import subprocess

ssh_sw_file = '../conf/ssh_sw'
ssh_sws_raw = []

topo_file = '../conf/fattree_outband_cloudlab.json'
topo = {}


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

with open(topo_file) as in_file:
    topo = byteify(json.load(in_file))

topo['switches_dpid_to_name'] = {}
topo['switches_name_to_dpid'] = {}

with open(ssh_sw_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_sws_raw.append(ret)

sl = len(ssh_sws_raw)
for i in range(0, sl):
    print 'switch %d' % i
    ret = ssh_sws_raw[i]
    mac = subprocess.check_output("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo cat /sys/class/net/sw/address" % (ret[2], ret[3]), shell=True)
    mac = mac[0: len(mac)-1]
    ms = mac.split(':')
    dpid = 'of:0000' + ms[0] + ms[1] + ms[2] + ms[3] + ms[4] + ms[5]
    name = 's' + str(i).zfill(3)
    topo['switches_dpid_to_name'][dpid] = name
    topo['switches_name_to_dpid'][name] = dpid

with open(topo_file, 'w') as out_file:
    json.dump(topo, out_file)
