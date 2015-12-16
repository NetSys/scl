import struct
import socket
import libopenflow_01 as of
from collections import defaultdict
from socket_utils import id2str
from pox.packet.addresses import IPAddr
from conf.const import RECV_BUF_SIZE, WINDOW


generate_of_seq = of.xid_generator()

SCLT_HELLO              = 0 # set up connection
SCLT_CLOSE              = 1 # close connection
SCLT_OF                 = 2 # normal of message
SCLT_LINK_RQST          = 3 # preriodic link request
SCLT_LINK_NOTIFY        = 4 # preriodic link reply
SCLT_FLOW_TABLE_RQST    = 5 # preriodic flow table request
SCLT_FLOW_TABLE_NOTIFY  = 6 # preriodic flow table reply

OFP_MAX_PORT_NAME_LEN = 16


def addheader(msg, type):
    return struct.pack('!BI', type, generate_of_seq()) + msg

def parseheader(msg):
    offset = 0
    type = ord(msg[offset])
    seq = ord(msg[offset+1]) << 24 | ord(msg[offset+2]) << 16 |\
          ord(msg[offset+3]) << 8 | ord(msg[offset+4])
    return type, seq, msg[offset+5:]

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

flow_table_status = of.xid_generator()


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

    def ofp_flow_mod_msg(self, nw_src, nw_dst, outport, cmd):
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
                        ret[conn_id].append(self.ofp_flow_mod_msg(
                            host1, host2, outport, of.OFPFC_MODIFY))
                    if self.sw_flow_tables[conn_id].table[host1][host2] is None:
                        del self.sw_flow_tables[conn_id].table[host1][host2]
            for host1, host in self.sw_flow_tables[conn_id].table.iteritems():
                for host2, outport in host.iteritems():
                    if flow_table.table[host1][host2] is None:
                        del flow_table.table[host1][host2]
                        ret[conn_id].append(self.ofp_flow_mod_msg(
                            host1, host2, outport, of.OFPFC_DELETE))
        return ret
