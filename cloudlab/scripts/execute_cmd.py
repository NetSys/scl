#! /usr/bin/python

import subprocess
import sys

if len(sys.argv) != 3:
    return

if sys.argv[1] == 'agents':
    ssh__file = '../conf/ssh_sw'
else if sys.argv[1] == 'hosts':
    ssh_file = '../conf/ssh_host'
else if sys.argv[1] == 'proxies':
    ssh_file = '../conf/ssh_ctrl'
ssh_raw = []

with open(ssh_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][:-1]
        ssh_raw.append(ret)

l = len(ssh_raw)

for i in range(0, l):
    print 'instance %d' % i
    ret = ssh_raw[i]
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo %s" % (ret[2], ret[3], sys.argv[2]), shell=True)
