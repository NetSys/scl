import struct
import libopenflow_01 as of


generate_of_seq = of.xid_generator()

SCLT_HELLO          = 0 # set up connection
SCLT_CLOSE          = 1 # close connection
SCLT_OF             = 2 # normal of message
SCLT_LINK_RQST      = 3 # preriodic link request
SCLT_LINK_NOTIFY    = 4 # preriodic link reply

OFP_MAX_PORT_NAME_LEN = 16


def addheader(msg, type):
    if type is SCLT_OF:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_HELLO:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_CLOSE:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_LINK_RQST:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_LINK_NOTIFY:
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
