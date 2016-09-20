#! /usr/bin/python

import sys
import argparse
from net import SclNet


parser = argparse.ArgumentParser(description='Test SCL with Mininet')
parser.add_argument('channel', choices=['tcp', 'udp'], default='udp', help='specify the channel type')
parser.add_argument('topology', choices=['fattree_outband', 'fattree_inband'], default='fattree_outband', help='specify the topology type')
parser.add_argument('application', choices=['shortest', 'te', 'clean'], default='shortest', help='specify the controller application type')

args = parser.parse_args()

if args.channel == 'tcp' and args.topology == 'fattree_inband':
    print 'tcp not supported for inband control'
    exit(1)

scl_net = SclNet(topo=args.topology, app=args.application, ch=args.channel)
scl_net.run()
scl_net.stop()
