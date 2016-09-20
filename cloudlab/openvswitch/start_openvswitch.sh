#! /bin/bash

# add br, add port, depends on your topology
ovs-vsctl add-br sw
ifconfig eth1 0
ifconfig eth2 0
ifconfig eth3 0
ifconfig eth4 0
ovs-vsctl add-port sw eth1
ovs-vsctl add-port sw eth2
ovs-vsctl add-port sw eth3
ovs-vsctl add-port sw eth4

ovs-vsctl set Bridge sw other-config:disable-in-band=true
ovs-vsctl set-fail-mode sw secure
ovs-vsctl set-controller sw tcp:127.0.0.1:6633
