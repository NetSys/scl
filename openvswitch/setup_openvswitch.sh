#! /bin/sh
#

apt-get install -y git python-simplejson python-qt4 python-twisted-conch automake autoconf libtool gcc build-essential openssl libssl-dev

./boot.sh
./configure --with-linux=/lib/modules/`uname -r`/build
make
make install

make modules_install

modprobe openvswitch

touch /usr/local/etc/ovs-vswitchd.conf
mkdir -p /usr/local/etc/openvswitch
ovsdb-tool create /usr/local/etc/openvswitch/conf.db /usr/local/share/openvswitch/vswitch.ovsschema


ovsdb-server --remote=punix:/usr/local/var/run/openvswitch/db.sock \
                     --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
                     --private-key=db:Open_vSwitch,SSL,private_key \
                     --certificate=db:Open_vSwitch,SSL,certificate \
                     --bootstrap-ca-cert=db:Open_vSwitch,SSL,ca_cert \
                     --log-file='../scl-agent/log/ovsdb-server.log' \
                     --pidfile --detach
ovs-vsctl --no-wait init
# enable vconn dbg logging and disable rate limits
ovs-vswitchd --log-file='../scl-agent/log/ovs-vswitchd.log' --verbose=vconn --pidfile --detach
ovs-appctl vlog/disable-rate-limit vconn
