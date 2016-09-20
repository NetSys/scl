# socket recv buf size
RECV_BUF_SIZE = 4096

# sequence number window
WINDOW = 1 << 31

# max open tcp connections
MAX_TCP_CONNS = 50

# link bandwidth (Mbps)
MAX_BANDWIDTH = 1

# OFPST_VENDOR vendor ID, randomly select a number
TE_VENDOR = 0xfffe

# udp broadcast address
UDP_BROADCAST_ADDR = '255.255.255.255'

# local connection configuration
local_ctrl_host = '127.0.0.1'
local_ctrl_port = 6633

# listening port
scl_proxy_port = 6000
scl_agent_port = 6000
