#! /usr/bin/python

import subprocess

ssh_ctrl_file = '../conf/ssh_ctrl'
ssh_ctrls_raw = []

with open(ssh_ctrl_file) as f:
    for i in f.readlines():
        ret = i.split(' ')
        ret[-1] = ret[-1][0: len(ret[-1])-1]
        ssh_ctrls_raw.append(ret)

l = len(ssh_ctrls_raw)

for i in range(0, l):
    print 'controller %d' % i
    ret = ssh_ctrls_raw[i]
    dst = ret[3] + ':~'
    subprocess.call("scp -o StrictHostKeyChecking=no -i your_key -P %s config_proxy.sh start_proxy.sh %s" % (ret[2], dst), shell=True)

for i in range(0, l):
    print 'controller %d' % i
    ret = ssh_ctrls_raw[i]
    subprocess.call("ssh -o StrictHostKeyChecking=no -i your_key -p %s %s sudo ./config_proxy.sh &" % (ret[2], ret[3]), shell=True)
