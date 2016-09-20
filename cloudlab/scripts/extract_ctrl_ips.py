#! /usr/bin/python

import ConfigParser
import json

ctrls_jail_file = '../conf/ctrls_jail'
ctrls_map_file = '../conf/ctrls_map'
net_cfg_file = '../conf/net.cfg'

jail_raw = []
mapping_raw = []
jail_dict = {}
mapping_dict = {}

agent_list = []
ip_list = []

with open(ctrls_jail_file) as jf:
    for i in jf.readlines():
        jail_raw.append(i)

with open(ctrls_map_file) as mf:
    for i in mf.readlines():
        mapping_raw.append(i)

for i in jail_raw:
    ret = i.split(' ')
    jail_dict[ret[3]] = ret[-1][0: len(ret[-1])-1]

for i in mapping_raw:
    ret = i.split(' ')
    mapping_dict[int(ret[1].split('-')[1])] = ret[3]

for i in range(0, 20):
    agent_list.append(jail_dict[mapping_dict[i]])

for i in range(0, 36):
    ip_list.append(jail_dict[mapping_dict[i]])

config = ConfigParser.ConfigParser()
config.read(net_cfg_file)
config.set('interfaces', 'agent_list', json.dumps(agent_list))
with open(net_cfg_file, 'wb') as cf:
    config.write(cf)
