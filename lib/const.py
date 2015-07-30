# scl tcp listening address
sw_scl_serv_host = '127.0.0.1'
sw_scl_serv_port = 6633

# scl udp mcast group
ctrl_scl_mcast_grp = '224.1.1.1'
ctrl_scl_mcast_port = 6644
ctrl_scl_intf = '192.168.1.1'
# controller listening address
ctrl_host = '127.0.0.1'
ctrl_port = 6633

# recv buf size
RECV_BUF_SIZE = 2048

# ovsdb unix path
OVSDB = '/var/run/openvswitch/db.sock'

# gossip protocol peer lists
peer_lists = [
        ('192.168.1.1', 6655),
        ('192.168.1.10', 6655)]
host_id = 0
