import struct
import libopenflow_01 as of


generate_of_seq = of.xid_generator()
generate_link_seq = of.xid_generator()

SCLT_HELLO          = 0 # set up connection
SCLT_CLOSE          = 1 # close connection
SCLT_OF             = 2 # normal of message
SCLT_LINK_RQST      = 3 # preriodic link request
SCLT_LINK_RPLY      = 4 # preriodic link reply

OFP_MAX_PORT_NAME_LEN = 16


def addheader(msg, type):
    if type is SCLT_OF:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_HELLO:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_CLOSE:
        return struct.pack('!BI', type, generate_of_seq()) + msg
    elif type is SCLT_LINK_RQST:
        return struct.pack('!BI', type, generate_link_seq()) + msg
    elif type is SCLT_LINK_RPLY:
        return struct.pack('!BI', type, generate_link_seq()) + msg


def parseheader(msg):
    offset = 0
    type = ord(msg[offset])
    seq = ord(msg[offset+1]) << 24 | ord(msg[offset+2]) << 16 |\
          ord(msg[offset+3]) << 8 | ord(msg[offset+4])
    return type, seq, msg[offset+5:]


class scl_link_state(object):
    def __init__(self):
        self.port = ''
        self.state = 0

    def pack(self, port, state):
        msg = ''
        port = str(port)
        if len(port) > OFP_MAX_PORT_NAME_LEN:
            # TODO: raise
            msg = port[0: OFP_MAX_PORT_NAME_LEN]
        for i in range(0, OFP_MAX_PORT_NAME_LEN - len(port)):
            msg = msg + '\0'
        msg = msg + port
        msg = msg + struct.pack('!I', state)
        return msg

    def unpack(self, msg):
        for i in range(0, OFP_MAX_PORT_NAME_LEN):
            self.port =  self.port + msg[i]
        port = self.port.split(b"\x00")
        self.port = port[len(port) - 1]
        offset = OFP_MAX_PORT_NAME_LEN
        self.state = ord(msg[offset]) << 24 | ord(msg[offset+1]) << 16 |\
                     ord(msg[offset+2]) << 8 | ord(msg[offset+3])


'''
scl header description

struct scl_header {
    uint8_t type;
    uint32_t seq;
};
SCL_ASSERT(sizeof(struct scl_header) == 5)

enum scl_type {
    SCLT_HELLO          = 0 /* set up connection */
    SCLT_CLOSE          = 1 /* close connection */
    SCLT_OF             = 2 /* normal of message */
    SCLT_LINK_RQST      = 3 /* preriodic link request */
    SCLT_LINK_RPLY      = 4 /* preriodic link reply */
};
'''
