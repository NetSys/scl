#!/bin/bash

echo config ovsdb for $1

mkdir -p /tmp/mininet-$1

if [ -e /tmp/mininet-$1/conf.db ]; then
   echo ovsdb already exists
else
   echo createing ovsdb
   ovsdb-tool create /tmp/mininet-$1/conf.db /usr/share/openvswitch/vswitch.ovsschema
fi

ovsdb-server /tmp/mininet-$1/conf.db \
-vconsole:emer \
-vsyslog:err \
-vfile:info \
--remote=punix:/tmp/mininet-$1/db.sock \
--remote=db:Open_vSwitch,Open_vSwitch,manager_options \
--unixctl=/tmp/mininet-$1/ovsdb-server.ctl \
--private-key=db:Open_vSwitch,SSL,private_key \
--certificate=db:Open_vSwitch,SSL,certificate \
--bootstrap-ca-cert=db:Open_vSwitch,SSL,ca_cert \
--no-chdir \
--log-file=/tmp/mininet-$1/ovsdb-server.log \
--pidfile=/tmp/mininet-$1/ovsdb-server.pid \
--detach \
--monitor

ovs-vsctl --db=unix:/tmp/mininet-$1/db.sock --no-wait init

echo starting ovs for $1

ovs-vswitchd unix:/tmp/mininet-$1/db.sock \
--unixctl=/tmp/mininet-$1/ovs-vswitchd.ctl \
-vconsole:emer \
-vsyslog:err \
-vfile:info \
--mlockall \
--no-chdir \
--log-file=/tmp/mininet-$1/ovs-vswitchd.log \
--pidfile=/tmp/mininet-$1/ovs-vswitchd.pid \
--detach \
--monitor
