import socket
import struct
from collections import defaultdict
from conf.const import MAX_TCP_CONNS, UDP_BROADCAST_ADDR


def ip2int(addr):
    return struct.unpack("!I", socket.inet_aton(addr))[0]

def int2ip(addr):
    return socket.inet_ntoa(struct.pack("!I", addr))

def id2str(conn_id):
    #return int2ip(conn_id >> 16) + ':' + str(conn_id % (1 << 16))
    return int2ip(conn_id)

def str2id(switch):
    #ip, port = switch.split(':')
    #return (ip2int(ip) << 16) + int(port)
    return ip2int(switch)

def id2name(conn_id):
    name = int2ip(conn_id).split('.')[2]
    for i in range(0, 3 - len(name)):
        name = '0' + name
    return 's' + name

def byteify(input):
    '''
    convert unicode from json.loads to utf-8
    '''
    if isinstance(input, dict):
        return {byteify(key): byteify(value) for key, value in input.iteritems()}
    elif isinstance(input, list):
        return [byteify(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input


class UdpConn(object):
    '''
    For scl on the switch side, connect to scl on the controller side
    '''
    def __init__(self, dst_host, dst_port):
        # To send msg outside, first checkout the host route
        self.dst_addr = (dst_host, dst_port)

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setblocking(0)            # non-blocking

    def recv(self, buf_size):
        data = self.sock.recv(buf_size)
        return data

    def send(self, msg):
        self.sock.send(msg, self.dst_addr)


class UdpFloodListener(object):
    def __init__(self, src_intf, src_port, dst_port):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.setblocking(0)            # non-blocking
        if not src_intf:
            self.sock.bind(('', src_port))
        else:
            self.sock.bind((src_intf, src_port))
        self.dst_addr = (UDP_BROADCAST_ADDR, dst_port)

    def recvfrom(self, buf_size):
        data, addr = self.sock.recvfrom(buf_size)
        return data, addr

    def recv(self, buf_size):
        data = self.sock.recv(buf_size)
        return data

    def send(self, msgs):
        if isinstance(msgs, list):
            for msg in msgs:
                self.sock.sendto(msg, self.dst_addr)
        else:
            self.sock.sendto(msgs, self.dst_addr)


class UdpMcastListener(object):
    '''
    For scl on the controller side, listening the multicast group
    '''
    def __init__(self, src_mcast_grp, src_mcast_port, mcast_intf=None,
            dst_mcast_grp=None, dst_mcast_port=None):
        self.sock = None
        self.src_grp = src_mcast_grp
        self.src_port = src_mcast_port
        self.intf = mcast_intf              # which interface to listen at
        self.dst_grp = dst_mcast_grp
        self.dst_port = dst_mcast_port
        if self.intf is None:                    # None means all interfaces
            self.intf = socket.INADDR_ANY
        self.dst_addr = defaultdict(lambda: None)

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setblocking(0)            # non-blocking
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 20)
        # Allow multiple copies of this program on one machine
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Tell the operating system to add the socket to the multicast group
        # on target interface.
        addrinfo = socket.getaddrinfo(self.src_grp, None)[0]
        group_bin = socket.inet_pton(addrinfo[0], addrinfo[4][0])
        mreq = group_bin + socket.inet_aton(self.intf)
        self.sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        self.sock.bind(('',self.src_port))

    def recvfrom(self, buf_size):
        data, addr = self.sock.recvfrom(buf_size) # addr = ('ip', port)
        addr_id = ip2int(addr[0])
        self.dst_addr[addr_id] = addr
        return data, addr_id

    def send_to_id(self, msgs, addr_id):
        if not self.dst_addr[addr_id]:
            ip, port = id2str(addr_id).split(':')
            addr = (ip, int(port))
            self.dst_addr[addr_id] = addr
        if isinstance(msgs, list):
            for msg in msgs:
                self.sock.sendto(msg, self.dst_addr[addr_id])
        else:
            self.sock.sendto(msgs, self.dst_addr[addr_id])

    def send_to_addr(self, msg, addr, port):
        self.sock.sendto(msg, (addr, port))

    def multicast(self, msgs, dst=False):
        # route add -host self.src_grp dev self.intf
        if not dst:
            if isinstance(msgs, list):
                for msg in msgs:
                    self.sock.sendto(msg, (self.src_grp, self.src_port))
            else:
                self.sock.sendto(msgs, (self.src_grp, self.src_port))
        else:
            if isinstance(msgs, list):
                for msg in msgs:
                    self.sock.sendto(msg, (self.dst_grp, self.dst_port))
            else:
                self.sock.sendto(msgs, (self.dst_grp, self.dst_port))


class TcpConn(object):
    '''
    For scl on the switch side, connect to switch.
    Or for scl on the controller side, connect to controller
    '''
    def __init__(self, dst_host, dst_port, sock=None, conn_id=None):
        self.sock = sock
        self.dst_addr = (dst_host, dst_port)
        self.connectted = False
        self.conn_id = conn_id

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(0)

    def recv(self, buf_size):
        msg = self.sock.recv(buf_size)
        return msg

    def send(self, msg):
        self.sock.send(msg)

    def isconnectted(self):
        err = self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        # EINPROGRESS ?
        if err is 0:
            self.connectted = True
            return True, err
        else:
            self.connectted = False
            return False, err

    def connect(self):
        if not self.connectted:
            try:
                self.open()
                self.sock.connect(self.dst_addr)
                self.connectted = True
                return True, 0
            except socket.error as serr:
                return False, serr
        else:
            return True, 0

    def close(self):
        if self.connectted:
            self.sock.close()
            self.connectted = False


class TcpConnsMulti2One(object):
    '''
    For scl on the controller side, connect to controller
    multiple sources to one destination
    '''
    def __init__(self, dst_host, dst_port):
        self.sock2conn = {}                     # k: v is sock: conn
        self.id2conn = {}                       # k: v is conn_id: conn
        self.dst_host = dst_host
        self.dst_port = dst_port

    def open(self, conn_id):
        conn = TcpConn(self.dst_host, self.dst_port, None, conn_id)
        ret, err = conn.connect()
        self.sock2conn[conn.sock] = conn
        self.id2conn[conn_id] = conn
        return ret, err

    def close(self, conn_id):
        self.id2conn[conn_id].close()
        del self.sock2conn[self.id2conn[conn_id].sock]
        del self.id2conn[conn_id]

    def recv(self):
        msg = self.sock.recv(1024)
        return msg

    def send(self, msg):
        self.sock.send(msg)


class TcpConnsOne2Multi(object):
    def __init__(self, dst_intfs, dst_port):
        self.intf2conn = defaultdict(lambda: None)  # k: v is intf: conn
        self.sock2conn = {}                         # k: v is sock: conn
        self.dst_intfs = dst_intfs
        self.dst_port = dst_port

    def open(self, intf):
        conn = TcpConn(intf, self.dst_port, None, intf)
        ret, err = conn.connect()
        self.intf2conn[intf] = conn
        self.sock2conn[conn.sock] = conn
        return ret, err

    def close(self, intf):
        self.intf2conn[intf].close()
        del self.sock2conn[self.intf2conn[intf].sock]
        del self.intf2conn[intf]


class TcpListener(object):
    '''
    For scl on the switch side, listen connections from switch
    '''
    def __init__(self, src_host, src_port):
        self.sock2conn = {}                     # k: v is sock: conn
        self.id2conn = {}                       # k: v is conn_id: conn
        self.sock = None
        self.host = src_host
        self.port = src_port
        self.open()

    def open(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(0)            # non-blocking
        self.sock.bind((self.host, self.port))
        self.sock.listen(MAX_TCP_CONNS)     # max open connections

    def accept(self):
        sock, addr = self.sock.accept()
        sock.setblocking(0)
        conn_id = ip2int(addr[0])
        conn = TcpConn(addr[0], addr[1], sock, conn_id)
        self.sock2conn[sock] = conn
        self.id2conn[conn_id] = conn
        return sock, conn_id

    def close(self, conn_id):
        self.id2conn[conn_id].close()
        del self.sock2conn[self.id2conn[conn_id].sock]
        del self.id2conn[conn_id]
