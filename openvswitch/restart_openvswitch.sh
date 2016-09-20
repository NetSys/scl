#! /bin/sh
#

kill `cd /usr/local/var/run/openvswitch && cat ovsdb-server.pid ovs-vswitchd.pid`

ovsdb-server --remote=punix:/usr/local/var/run/openvswitch/db.sock \
                     --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
                     --private-key=db:Open_vSwitch,SSL,private_key \
                     --certificate=db:Open_vSwitch,SSL,certificate \
                     --bootstrap-ca-cert=db:Open_vSwitch,SSL,ca_cert \
                     --log-file='../scl-agent/log/ovsdb-server.log' \
                     --pidfile --detach
# enable vconn dbg logging and disable rate limits
ovs-vswitchd --log-file='../scl-agent/log/ovs-vswitchd.log' --verbose=vconn --pidfile --detach
ovs-appctl vlog/disable-rate-limit vconn
