#! /usr/bin/python

from net import SclNet

scl_net = SclNet(topo='fattreeoutband', app='te')
#scl_net = SclNet()
scl_net.run()
scl_net.stop()
