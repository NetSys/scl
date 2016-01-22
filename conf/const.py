# scl tcp listening address
scl_agent_serv_host = '127.0.0.1'
scl_agent_serv_port = 6633
scl_agent_mcast_grp = '224.1.1.3'
scl_agent_mcast_port = 6666
scl_agent_intf = '192.168.1.100'      # depends on host

# scl udp mcast group
scl_proxy_mcast_grp = '224.1.1.1'
scl_proxy_mcast_port = 6644
scl_proxy_intf = '192.168.1.1'      # depends on host
# controller listening address
ctrl_host = '127.0.0.1'
ctrl_port = 6633

# recv buf size
RECV_BUF_SIZE = 4096
# version number window
WINDOW = 1 << 31

# ovsdb unix path
OVSDB = '/var/run/openvswitch/db.sock'

# link bandwidth (Mbps)
MAX_BANDWIDTH = 1

# OFPST_VENDOR vendor ID, randomly select a number
TE_VENDOR = 0xfffe

# gossip protocol
scl_gossip_mcast_grp = '224.1.1.2'
scl_gossip_mcast_port = 6655
scl_gossip_intf = '192.168.1.1'     # depends on host
peer_lists = [
        ('192.168.1.1', 6655),
        ('192.168.1.10', 6655)]
hosts_num = 2
host_id = 0
