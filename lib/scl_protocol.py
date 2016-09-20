import struct
import socket
import libopenflow_01 as of
from collections import defaultdict
from socket_utils import id2str, ip2int
from pox.packet.addresses import IPAddr
from conf.const import RECV_BUF_SIZE, WINDOW, MAX_BANDWIDTH


generate_scl_seq = of.xid_generator()
flow_table_status = of.xid_generator()
flow_stats_rqst_seq = of.xid_generator()

SCL_PROXY = 0
SCL_AGENT = 1
my_type = None
my_addr = ''                    # intf ip of local node, set by Scl2Scl
ALL_CTRL_ADDR = '0.0.0.0'       # intf ip for all controllers
ALL_SW_ADDR = '0.0.0.1'         # intf ip for all switches
received_pkts = set()

SCLT_HELLO              = 1     # set up connection
SCLT_CLOSE              = 2     # close connection
SCLT_OF_PROXY           = 3     # normal of message
SCLT_OF_AGENT           = 4     # normal of message
SCLT_LINK_RQST          = 5     # periodic link request
SCLT_LINK_NOTIFY        = 6     # periodic link reply
SCLT_FLOW_TABLE_RQST    = 7     # periodic flow table request
SCLT_FLOW_TABLE_NOTIFY  = 8     # periodic flow table reply
SCLT_FLOW_STATS_RQST    = 9     # periodic flow stats request
SCLT_FLOW_STATS_REPLY   = 10    # periodic flow stats reply
SCLT_GOSSIP_SYN         = 11    # periodic log digest broadcast
SCLT_GOSSIP_ACK         = 12    # missing log response if existing

OFP_MAX_PORT_NAME_LEN = 16


def flood_and_process_check(src_addr, dst_addr, ver):
    # returned variables: flood, process
    if my_type == SCL_AGENT:
        packet_id = src_addr + dst_addr + str(ver)
        if packet_id in received_pkts:
            return False, False
        else:
            received_pkts.add(packet_id)
        if dst_addr == my_addr:
            return False, True
        elif dst_addr == ALL_SW_ADDR:
            return True, True
        else:
            return True, False
    elif my_type == SCL_PROXY:
        if dst_addr != my_addr and dst_addr != ALL_CTRL_ADDR:
            return False, False
        else:
            return False, True


#---------------------------packet level communication-------------------------#

SCL_UDP_HEADER_SIZE = 7
max_scl_data_length = RECV_BUF_SIZE - SCL_UDP_HEADER_SIZE

# maintain states of multiple connections
# scl udp header format (size: byte)
#   SCLT(1) SRC_ADDR(4) DST_ADDR(4) VERSION(4) FRAGMENT_ID(1) FRAGMENT_NUM(1)
udp_buffs = defaultdict(lambda: defaultdict(lambda: None)) # [con][idx] --> data
version = defaultdict(lambda: None)     # [con] --> ver
frag_num = defaultdict(lambda: None)    # [con] --> num of msg fragments


def scl_udp_pack(data, sclt, src_addr, dst_addr):
    # the returned value is a list
    frags = []
    while len(data) > max_scl_data_length:
        frags.append(data[0: max_scl_data_length])
        data = data[max_scl_data_length:]
    frags.append(data)
    frag_num = len(frags)
    current_ver = generate_scl_seq()
    for i in xrange(0, frag_num):
        # addheader
        frags[i] = struct.pack('!B', sclt) + \
                socket.inet_aton(src_addr) + \
                socket.inet_aton(dst_addr) + \
                struct.pack('!IBB', current_ver, i, frag_num) + frags[i]
    return frags

def scl_udp_header_parse(msg):
    offset = 0
    sclt = ord(msg[offset])
    offset += 1
    src_addr = socket.inet_ntoa(msg[offset: offset+4])
    offset += 4
    dst_addr = socket.inet_ntoa(msg[offset: offset+4])
    offset += 4
    ver = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
          ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset += 4
    idx = ord(msg[offset])
    offset += 1
    num = ord(msg[offset])
    offset += 1
    return sclt, src_addr, dst_addr, ver, idx, num, msg[offset:]

def check_completeness(con):
    if len(udp_buffs[con]) == frag_num[con]:
        complete_msg = ''
        for i in xrange(0, frag_num[con]):
            complete_msg += udp_buffs[con][i]
        del version[con]
        del frag_num[con]
        del udp_buffs[con]
        return complete_msg
    else:
        return None

def scl_udp_unpack(msg):
    # returned variables: flood, sclt, conn_id, msg
    #                (proxy will ignore the flood variable)
    # calling functions decide if to continue to process
    # according to msg variable, None means passed
    sclt, src_addr, dst_addr, ver, idx, num, data = scl_udp_header_parse(msg)
    flood, process = flood_and_process_check(src_addr, dst_addr, ver)
    if not process:
        return flood, None, None, None
    con = ip2int(src_addr)
    if not version[con]:
        # new version, last msg has been processed
        version[con] = ver
        frag_num[con] = num
        udp_buffs[con][idx] = data
        return flood, sclt, con, check_completeness(con)
    else:
        if ver == version[con]:
            # the same version, last msg to be processed
            if frag_num[con] != num:
                # ! fragments in the sameme version have different fragment num
                del version[con]
                del frag_num[con]
                del udp_buffs[con]
                return flood, sclt, con, None
            else:
                udp_buffs[con][idx] = data
                return flood, sclt, con, check_completeness(con)
        elif (ver > version[con] and ver - version[con] < WINDOW) or \
             (ver < version[con] and version[con] - ver > WINDOW):
            # new version, discard current states, update ver and data
            version[con] = ver
            frag_num[con] = num
            del udp_buffs[con]
            udp_buffs[con][idx] = data
            return flood, sclt, con, check_completeness(con)
        else:
            return flood, sclt, con, None


#----------------------------flow level communication--------------------------#

SCL_TCP_HEADER_SIZE = 15

# maintain states of multiple connections
# scl tcp header format (size: byte)
#   SCLT(1) LENGTH(2) SRC_ADDR(4) DST_ADDR(4) VERSION(4)
tcp_buffs = defaultdict(lambda: None)       # [con] --> data


def scl_tcp_close(conn_id):
    # clean the bufffer if it exists
    if conn_id in tcp_buffs:
        del tcp_buffs[conn_id]

def scl_tcp_pack(data, sclt, src_addr, dst_addr):
    length = len(data) + SCL_TCP_HEADER_SIZE
    current_ver = generate_scl_seq()
    msg = struct.pack('!BH', sclt, length)
    msg += socket.inet_aton(src_addr)
    msg += socket.inet_aton(dst_addr)
    msg += struct.pack('!I', current_ver)
    msg += data
    return msg

def scl_tcp_header_parse(msg):
    offset = 0
    sclt = ord(msg[offset])
    offset += 1
    length = ord(msg[offset]) << 8 | ord(msg[offset+1])
    offset += 2
    src_addr = socket.inet_ntoa(msg[offset: offset+4])
    offset += 4
    dst_addr = socket.inet_ntoa(msg[offset: offset+4])
    offset += 4
    ver = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
          ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset += 4
    return sclt, length, src_addr, dst_addr, ver, msg[offset:]

def scl_tcp_unpack(data, conn_id):
    msgs = []
    tmp_buff = tcp_buffs[conn_id] if tcp_buffs[conn_id] else ''
    tmp_buff += data
    buff_length = len(tmp_buff)
    # parse multiple msgs in buff
    offset = 0
    while buff_length - offset >= SCL_TCP_HEADER_SIZE:
        msg_length = ord(tmp_buff[offset + 1]) << 8 | ord(tmp_buff[offset + 2])
        if buff_length - offset < msg_length:
            break
        sclt, length, src_addr, dst_addr, ver, msg = scl_tcp_header_parse(
                tmp_buff[offset: offset + msg_length])
        flood, process = flood_and_process_check(src_addr, dst_addr, ver)
        if not process:
            msgs.append([flood, None, None])
        else:
            msgs.append([flood, sclt, msg])
        offset = offset + msg_length
    tcp_buffs[conn_id] = tmp_buff[offset:]
    return msgs

def link_state_pack(intf, port_no, state, version):
    msg = ''
    intf = str(intf)
    if len(intf) > OFP_MAX_PORT_NAME_LEN:
        msg = intf[0: OFP_MAX_PORT_NAME_LEN]
    else:
        for i in range(0, OFP_MAX_PORT_NAME_LEN - len(intf)):
            msg = msg + '\0'
        msg = msg + intf
    msg = msg + struct.pack('!H', port_no)
    msg = msg + struct.pack('!I', state)
    msg = msg + struct.pack('!I', version)
    return msg

def link_state_unpack(msg):
    intf = ''
    for i in range(0, OFP_MAX_PORT_NAME_LEN):
        intf = intf + msg[i]
    intf = intf.split(b"\x00")
    intf = intf[-1]
    offset = OFP_MAX_PORT_NAME_LEN
    port_no = ord(msg[offset]) << 8 | ord(msg[offset+1])
    offset = offset + 2
    state = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
            ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset = offset + 4
    version = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
              ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    return intf, port_no, state, version

def flow_entry_pack(version, host1, host2, outport):
    msg = ''
    msg += struct.pack('!I', version)
    msg += socket.inet_aton(host1)
    msg += socket.inet_aton(host2)
    msg += struct.pack('!H', outport)
    return msg

def flow_entry_unpack(msg):
    version = ord(msg[0]) << 24 | ord(msg[1]) << 16 |\
              ord(msg[2]) << 8 | ord(msg[3])
    msg = msg[4:]
    host1 = socket.inet_ntoa(msg[0:4])
    msg = msg[4:]
    host2 = socket.inet_ntoa(msg[0:4])
    msg = msg[4:]
    outport = ord(msg[0]) << 8 | ord(msg[1])
    return version, host1, host2, outport

def flow_stats_rqst_pack(addr_id, seq, ofp_stats_msg):
    msg = ''
    msg += socket.inet_aton(addr_id)
    msg += struct.pack('!I', seq)
    msg += ofp_stats_msg.pack()
    return msg

def flow_stats_rqst_unpack(msg):
    addr_id = socket.inet_ntoa(msg[0:4])
    msg = msg[4:]
    seq = ord(msg[0]) << 24 | ord(msg[1]) << 16 |\
          ord(msg[2]) << 8 | ord(msg[3])
    ofp_stats_msg = msg[4:]
    return addr_id, seq, ofp_stats_msg

def flow_stats_rply_pack(addr_id, seq, sec, nsec, ofp_stats_msg):
    msg = ''
    msg += socket.inet_aton(addr_id)
    msg += struct.pack('!I', seq)
    msg += struct.pack('!I', sec)
    msg += struct.pack('!I', nsec)
    msg += ofp_stats_msg
    return msg

def flow_stats_rply_unpack(msg):
    addr_id = socket.inet_ntoa(msg[0:4])
    msg = msg[4:]
    offset = 0
    seq = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
          ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset += 4
    sec = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
          ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset += 4
    nsec = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
          ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset += 4
    ofp_stats_msg = msg[offset: ]
    return addr_id, seq, sec, nsec, ofp_stats_msg

def parse_ofp_flow_stats_reply_msg(raw_msg):
    msg = of.ofp_stats_reply()
    msg.unpack(raw_msg)
    assert msg.header_type == of.OFPT_STATS_REPLY and msg.type == of.OFPST_FLOW
    return msg


class SwitchLinkEvents(object):
    def __init__(self):
        self.events = {}
        self.versions = {}
        self.states = {}
        self.port_nos = {}

    def update(self, intf, port_no, state):
        if intf not in self.events:
            self.events[intf] = of.xid_generator()
        self.versions[intf] = self.events[intf]()
        self.states[intf] = state
        self.port_nos[intf] = port_no
        return link_state_pack(intf, port_no, state, self.versions[intf])

    def current_events(self):
        msgs = []
        for intf in self.events:
            msgs.append(
                link_state_pack(
                intf, self.port_nos[intf],
                self.states[intf], self.versions[intf]))
        return msgs


class FlowTable(object):
    def __init__(self, logger):
        self.reset()
        self.logger = logger

    def update_version(self):
        self.version = flow_table_status()

    def reset(self):
        # [host1][host2] --> action
        self.table = defaultdict(lambda: defaultdict(lambda: None))
        self.update_version()

    def modify(self, host1, host2, outport):
        self.table[host1][host2] = outport
        self.update_version()

    def delete(self, host1, host2):
        if self.table[host1][host2]:
            del self.table[host1][host2]
        else:
            # table[host1][host2] is None
            del self.table[host1][host2]
        self.update_version()

    def update(self, msg):
        if msg.command == of.OFPFC_MODIFY:
            self.modify(
                    msg.match.nw_src.toStr(), msg.match.nw_dst.toStr(),
                    msg.actions[0].port)
        elif msg.command == of.OFPFC_DELETE:
            self.delete(msg.match.nw_src.toStr(), msg.match.nw_dst.toStr())

    def current_flow_entries(self):
        msgs = []
        for host1, host in self.table.iteritems():
            for host2, outport in host.iteritems():
                msgs.append(flow_entry_pack(self.version, host1, host2, outport))
        return msgs


class FlowTableDB(object):
    '''
    overwrite flow_table, no history
    '''
    def __init__(self, logger):
        self.ctrl_flow_tables = {}
        self.sw_flow_tables = {}
        self.sw_flow_table_versions = {}
        self.logger = logger

    def open(self, conn_id):
        self.ctrl_flow_tables[conn_id] = FlowTable(self.logger)
        self.sw_flow_tables[conn_id] = FlowTable(self.logger)
        self.sw_flow_table_versions[conn_id] = -1

    def delete(self, conn_id):
        if conn_id in self.ctrl_flow_tables.keys():
            del self.ctrl_flow_tables[conn_id]
        if conn_id in self.sw_flow_tables.keys():
            del self.sw_flow_tables[conn_id]
        if conn_id in self.sw_flow_table_versions.keys():
            del self.sw_flow_table_versions[conn_id]

    def show(self):
        s = 'ctrl_flow_tables:'
        for conn_id, flow_table in self.ctrl_flow_tables.iteritems():
            s = s + '\n' + id2str(conn_id) + '\n'
            for host1, host in flow_table.table.iteritems():
                for host2, outport in host.iteritems():
                    s = s + host1 + '-->' + host2 + ' outport:%d' % outport + ';'
        s += '\nsw_flow_tables:'
        for conn_id, flow_table in self.sw_flow_tables.iteritems():
            s = s + '\n' + id2str(conn_id) + '\n'
            for host1, host in flow_table.table.iteritems():
                for host2, outport in host.iteritems():
                    s = s + host1 + '-->' + host2 + ' outport:%d' % outport + ';'
        return s

    def ofp_msg_update(self, conn_id, msg):
        self.ctrl_flow_tables[conn_id].update(msg)

    def sw_notify_update(self, conn_id, version, host1, host2, outport):
        if version == self.sw_flow_table_versions[conn_id]:
            self.sw_flow_tables[conn_id].modify(host1, host2, outport)
        elif (version > self.sw_flow_table_versions[conn_id] and\
              version - self.sw_flow_table_versions[conn_id] < WINDOW) or\
             (version < self.sw_flow_table_versions[conn_id] and\
              self.sw_flow_table_versions[conn_id] - version > WINDOW):
            self.sw_flow_table_versions[conn_id] = version
            self.sw_flow_tables[conn_id].reset()
            self.sw_flow_tables[conn_id].modify(host1, host2, outport)

    def _create_ofp_flow_mod_msg(self, nw_src, nw_dst, outport, cmd):
        msg = of.ofp_flow_mod(command = cmd)
        msg.match.dl_type = 0x800
        msg.match.nw_src = IPAddr(nw_src)
        msg.match.nw_dst = IPAddr(nw_dst)
        msg.priority = 50000    # hard code
        msg.actions.append(of.ofp_action_output(port = outport))
        return msg

    def flow_tables_diff(self):
        ret = defaultdict(lambda: None)
        for conn_id, flow_table in self.ctrl_flow_tables.iteritems():
            ret[conn_id] = []
            for host1, host in flow_table.table.iteritems():
                for host2, outport in host.iteritems():
                    if self.sw_flow_tables[conn_id].table[host1][host2] != outport:
                        ret[conn_id].append(self._create_ofp_flow_mod_msg(
                            host1, host2, outport, of.OFPFC_MODIFY))
                    if self.sw_flow_tables[conn_id].table[host1][host2] is None:
                        del self.sw_flow_tables[conn_id].table[host1][host2]
            for host1, host in self.sw_flow_tables[conn_id].table.iteritems():
                for host2, outport in host.iteritems():
                    if flow_table.table[host1][host2] is None:
                        del flow_table.table[host1][host2]
                        ret[conn_id].append(self._create_ofp_flow_mod_msg(
                            host1, host2, outport, of.OFPFC_DELETE))
        return ret


class FlowStatsDB(object):
    '''
    short history, calculate throughtput
    '''
    def __init__(self, logger):
        self.flow_stats = {}    # [sw][seq][(src, dst)] --> (timestamp, bytes)
        self.logger = logger
        self.current_seq = -1
        self.previous_seq_received = defaultdict(lambda: True)

    def open(self, conn_id):
        self.flow_stats[conn_id] = {}

    def delete(self, conn_id):
        if conn_id in self.flow_stats.keys():
            del self.flow_stats[conn_id]

    def _create_ofp_flow_stats_request_msg(
            self, xid=None, match=None, table_id=0xff, out_port=of.OFPP_NONE):
        msg = of.ofp_stats_request()
        msg.body = of.ofp_flow_stats_request()
        if xid:
            msg.xid = xid
        if match is None:
          match = of.ofp_match()
        msg.body.match = match
        msg.body.table_id = table_id
        msg.body.out_port = out_port
        return msg

    def create_scl_flow_stats_rqst(self, addr_id):
        # periodically create new scl flow stats rqst msg and send it
        # if the previous probe is not acknowledged
        # we increase its estimated value exponentially? or average?
        # we offload the penalty process to application
        seq = flow_stats_rqst_seq()
        for conn_id in self.flow_stats.keys():
            if not self.previous_seq_received[conn_id]:
                self.update(conn_id)
            else:
                self.previous_seq_received[conn_id] = False
        self.current_seq = seq
        return flow_stats_rqst_pack(
                addr_id, seq, self._create_ofp_flow_stats_request_msg(xid=seq))

    def update(self, conn_id, seq=None, timestamp=None, ofp_stats_rply_msg_body=None):
        # seq is None, we estimate
        # seq < current_seq means timeout, we discard it
        if seq != None and seq < self.current_seq:
            return
        if conn_id not in self.flow_stats:
            self.flow_stats[conn_id] = {}

        # estimate
        if seq == None:
            if self.current_seq not in self.flow_stats[conn_id]:
                self.flow_stats[conn_id][self.current_seq] = {}
            return

        # we get the probe value in time
        assert seq == self.current_seq
        self.previous_seq_received[conn_id] = True
        if seq not in self.flow_stats[conn_id]:
            self.flow_stats[conn_id][seq] = {}
        for flow in ofp_stats_rply_msg_body:
            if flow.match.dl_type != 0x0800:
                continue
            nw_src = flow.match.nw_src.toStr()
            nw_dst = flow.match.nw_dst.toStr()
            if (nw_src, nw_dst) not in self.flow_stats[conn_id][seq]:
                self.flow_stats[conn_id][seq][(nw_src, nw_dst)] = {}
            self.flow_stats[conn_id][seq][(nw_src, nw_dst)] =\
                    (timestamp, flow.byte_count)

    def check_tm(self):
        traffic_amount1 = {}    # [sw][(nw_src, nw_dst)] --> (timestamp, bytes)
        traffic_amount2 = {}    # [sw][(nw_src, nw_dst)] --> (timestamp, bytes)

        traffic_matrices = {}   # [sw][nw_src][nw_dst] --> throughtput
                                # feasible to be converted to binary data
        upcall = False
        for conn_id in self.flow_stats:
            sw = id2str(conn_id)
            traffic_amount1[sw] = {}
            traffic_amount2[sw] = {}
            traffic_matrices[sw] = {}
            seqs = sorted(self.flow_stats[conn_id].keys())
            for seq in seqs:
                for pair in self.flow_stats[conn_id][seq]:
                    if pair not in traffic_amount1[sw]:
                        traffic_amount1[sw][pair] = self.flow_stats[conn_id][seq][pair]
                    else:
                        traffic_amount2[sw][pair] = self.flow_stats[conn_id][seq][pair]
            for pair in traffic_amount1[sw]:
                if pair in traffic_amount2[sw]:
                    throughtput =\
                            (traffic_amount2[sw][pair][1] - traffic_amount1[sw][pair][1]) * 8 /\
                            (traffic_amount2[sw][pair][0] - traffic_amount1[sw][pair][0])
                    if pair[0] not in traffic_matrices[sw]:
                        traffic_matrices[sw][pair[0]] = {}
                    traffic_matrices[sw][pair[0]][pair[1]] = throughtput
                    upcall = True
        # clear flow_stats after checking
        for conn_id in self.flow_stats:
            self.flow_stats[conn_id] = {}
        ret = traffic_matrices if upcall == True else None
        return ret
