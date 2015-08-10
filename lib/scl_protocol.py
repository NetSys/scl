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

def link_state_pack(port, state, version):
    msg = ''
    port = str(port)
    if len(port) > OFP_MAX_PORT_NAME_LEN:
        msg = port[0: OFP_MAX_PORT_NAME_LEN]
    for i in range(0, OFP_MAX_PORT_NAME_LEN - len(port)):
        msg = msg + '\0'
    msg = msg + port
    msg = msg + struct.pack('!I', state)
    msg = msg + struct.pack('!I', version)
    return msg

def link_state_unpack(msg):
    port = ''
    for i in range(0, OFP_MAX_PORT_NAME_LEN):
        port = port + msg[i]
    port = port.split(b"\x00")
    port = port[len(port) - 1]
    offset = OFP_MAX_PORT_NAME_LEN
    state = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
            ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    offset = offset + 4
    version = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
              ord(msg[offset+2]) << 8 | ord(msg[offset+3])
    return port, state, version


class SwitchLinkEvents(object):
    def __init__(self):
        self.events = {}
        self.version = {}
        self.states = {}

    def update(self, port, state):
        if port not in self.events:
            self.events[port] = of.xid_generator()
        self.version[port] = self.events[port]()
        self.states[port] = state
        return link_state_pack(port, state, self.version[port])

    def current_events(self):
        msgs = []
        for port in self.events:
            msgs.append(
                link_state_pack(
                port, self.states[port], self.version[port]))
        return msgs
