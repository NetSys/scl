import struct
import libopenflow_01 as of


generate_seq = of.xid_generator()

SCLT_HELLO          = 0 # set up connection
SCLT_CLOSE          = 1 # close connection
SCLT_OF             = 2 # normal of message
SCLT_LINK_RQST      = 3 # preriodic link request*


def addheader(msg, type):
    return struct.pack('!BI', type, generate_seq()) + msg

def parseheader(msg):
    offset = 0
    type = ord(msg[offset])
    seq = ord(msg[offset+1]) << 24 | ord(msg[offset+2]) << 16 |\
          ord(msg[offset+3]) << 8 | ord(msg[offset+4])
    return type, seq, msg[offset+5:]

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
    SCLT_OF             = 2 /* normal of message*/
    SCLT_LINK_RQST      = 3 /* preriodic link request*/
};
'''
