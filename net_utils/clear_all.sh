#! /bin/bash

SW=$1
echo clear ovs for $SW

ovs-vsctl --db=unix:/tmp/mininet-$SW/db.sock del-br $SW

kill `cat /tmp/mininet-$SW/ovsdb-server.pid`
kill `cat /tmp/mininet-$SW/ovs-vswitchd.pid`
