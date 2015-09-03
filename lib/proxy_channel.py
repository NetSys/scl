import Queue
import errno
from conf.const import RECV_BUF_SIZE
from socket_utils import *
from gossiper import LinkLog
import libopenflow_01 as of
import scl_protocol as scl


ECHO_TIMEOUT = 10

# some functions from pox controller
# pox/pox/openflow/util.py
# pox/pox/openflow/of_01.py
#----------------------------------------------------------------------------#
def make_type_to_unpacker_table():
    """
    Returns a list of unpack methods.

    The resulting list maps OpenFlow types to functions which unpack
    data for those types into message objects.
    """
    top = max(of._message_type_to_class)
    r = [of._message_type_to_class[i].unpack_new for i in range(0, top)]
    return r

unpackers = make_type_to_unpacker_table()

def handle_HELLO(scl, conn, msg):
    scl.logger.debug('ofp_handshake: hello received')
    hello = of.ofp_hello()
    scl.streams.upstreams[conn.conn_id].put(hello.pack())

def handle_ECHO_REPLY(scl, conn, msg):
    if scl.streams.ofp_echo_ids[conn.conn_id] != msg.xid:
        scl.logger.error(
            'echo err: the connection to controller is closed by scl_proxy, '
            'echo_rqst_xid: %d, while echo_rply_xid: %d, conn_id: %d' % (
                scl.streams.ofp_echo_ids[conn.conn_id], msg.xid, conn.conn_id))
        scl.clean_connection(conn.sock, conn.conn_id)
    else:
        scl.logger.debug('conn_id: %d, ofp_echo_reply received' % conn.conn_id)
        scl.streams.ofp_echo_times[conn.conn_id] = 0

def handle_ECHO_REQUEST(scl, conn, msg):
    reply = msg
    reply.header_type = of.OFPT_ECHO_REPLY
    scl.streams.upstreams[conn.conn_id].put(reply.pack())

def handle_FEATURES_REQUEST(scl, conn, msg):
    scl.logger.debug('ofp_handshake: features_request received')
    reply = of.ofp_features_reply()
    reply.xid = msg.xid
    switch = id2str(conn.conn_id)
    switch_name = scl.streams.link_log.links(switch)[0].split('-')[0]
    reply.datapath_id = int(switch_name[1:])
    scl.streams.upstreams[conn.conn_id].put(reply.pack())

def handle_SET_CONFIG(scl, conn, msg):
    pass

def handle_FLOW_MOD(scl2ctrl, conn, msg):
    # FIXME: to reply packet_in, right?
    if scl2ctrl.streams.ofp_connected[conn.conn_id]:
        # add scl header to msg, put it into downstreams
        scl2ctrl.streams.downstreams[conn.conn_id].put(
            scl.addheader(msg.pack(), scl.SCLT_OF))

def handle_BARRIER_REQUEST(scl, conn, msg):
    reply = msg
    reply.header_type = of.OFPT_BARRIER_REPLY
    scl.streams.upstreams[conn.conn_id].put(reply.pack())
    scl.logger.debug('ofp_handshake: barrier_requset received')
    scl.logger.debug('ofp_handshake: successful')
    scl.streams.ofp_connected[conn.conn_id] = True
    # transfer temp data from handshake_queues to upstreams
    while not scl.streams.handshake_queues[conn.conn_id].empty():
        data = scl.streams.handshake_queues[conn.conn_id].get()
        scl.streams.upstreams[conn.conn_id].put(data)


# A list, where the index is an OFPT, and the value is a function to
# call for that type
# This is generated automatically based on handlerMap
handlers = []

# Message handlers
handlerMap = {
    of.OFPT_HELLO : handle_HELLO,
    of.OFPT_ECHO_REQUEST : handle_ECHO_REQUEST,
    of.OFPT_ECHO_REPLY : handle_ECHO_REPLY,
    of.OFPT_FEATURES_REQUEST : handle_FEATURES_REQUEST,
    of.OFPT_SET_CONFIG : handle_SET_CONFIG,
    of.OFPT_FLOW_MOD : handle_FLOW_MOD,
    of.OFPT_BARRIER_REQUEST : handle_BARRIER_REQUEST,
}

def _set_handlers ():
    handlers.extend([None] * (1 + sorted(handlerMap.keys(),reverse=True)[0]))
    for h in handlerMap:
        handlers[h] = handlerMap[h]
#----------------------------------------------------------------------------#


class Streams(object):
    '''
    data received or to be sent
    '''
    def __init__(self, host_id, hosts_num):
        self.upstreams = {}         # conn_id: data_to_be_sent_to_controller
        self.downstreams = {}       # conn_id: data_to_be_sent_to_scl_agent
        self.last_of_seqs = {}      # conn_id: last_connection_sequence_num
        self.handshake_queues = {}  # store temp switch msgs while of handshake
        self.ofp_connected = {}
        self.ofp_echo_times = {}
        self.ofp_echo_ids = {}
        self.link_log = LinkLog(host_id, hosts_num)

    def downstreams_empty(self):
        for k in self.downstreams:
            if not self.downstreams[k].empty():
                return False
        return True

    def upcall_link_status(self, switch, link, state):
        port_status = of.ofp_port_status()
        port_status.reason = of.OFPPR_MODIFY
        sw_name, port_name, port_no = link.split('-')
        port_status.desc.port_no = int(port_no)
        port_status.desc.name = sw_name + '-' + port_name
        port_status.desc.state = state
        if self.ofp_connected[str2id(switch)]:
            self.upstreams[str2id(switch)].put(port_status.pack())
        else:
            self.handshake_queues[str2id(switch)].put(port_status.pack())

    def open(self, conn_id, of_seq):
        self.upstreams[conn_id] = Queue.Queue()
        self.downstreams[conn_id] = Queue.Queue()
        self.last_of_seqs[conn_id] = of_seq
        self.handshake_queues[conn_id] = Queue.Queue()
        self.ofp_connected[conn_id] = False
        self.ofp_echo_ids[conn_id] = 0
        self.ofp_echo_times[conn_id] = 0
        self.link_log.open(id2str(conn_id))

    def delete(self, conn_id):
        del self.upstreams[conn_id]
        del self.downstreams[conn_id]
        del self.last_of_seqs[conn_id]
        del self.handshake_queues[conn_id]
        del self.ofp_connected[conn_id]
        del self.ofp_echo_ids[conn_id]
        del self.ofp_echo_times[conn_id]
        self.link_log.delete(id2str(conn_id))


class Scl2Ctrl(object):
    '''
    channel from scl to controller, containing multiple connections
    each connection corresponding to a switch connection
    '''
    def __init__(self, ctrl_host, ctrl_port, timer, streams, logger):
        self.tcp_conns = TcpConns(ctrl_host, ctrl_port)
        self.logger = logger
        self.streams = streams
        self.timer = timer
        self.inputs = []
        self.outputs = []
        _set_handlers()

    def open(self, conn_id, seq):
        ret, err = self.tcp_conns.open(conn_id)
        sock = self.tcp_conns.id2conn[conn_id].sock
        # add connecting socket to checking list (outputs)
        self.outputs.append(sock)
        self.streams.open(conn_id, seq)
        if ret:
            self.logger.info(
                'connection to controller successful, conn_id: %d', conn_id)
            self.inputs.append(sock)
        elif err.errno is not errno.EINPROGRESS:
            self.logger.error(
                'connecting to controller fails, errno %d' % err.errno)

    def adjust_outputs(self):
        '''
        when stream is empty, remove the corresponding socket from outputs.
        if writeable socket is put into outputs directly, select will be called
        more frequentlty and the cpu usage may be 100%.
        '''
        for conn_id in self.tcp_conns.id2conn:
            conn = self.tcp_conns.id2conn[conn_id]
            if conn.connectted:
                if not self.streams.upstreams[conn_id].empty()\
                        and conn.sock not in self.outputs:
                    self.outputs.append(conn.sock)
                elif self.streams.upstreams[conn_id].empty()\
                        and conn.sock in self.outputs:
                    self.outputs.remove(conn.sock)

    def clean_connection(self, sock, conn_id):
        '''
        clean up the closed tcp connection
        '''
        if sock in self.outputs:
            self.outputs.remove(sock)
        if sock in self.inputs:
            self.inputs.remove(sock)
        self.streams.delete(conn_id)
        self.tcp_conns.close(conn_id)

    def handle_of_msg(self, conn, data):
        '''
        parse of openflow messages
        handshake
        put data into downstream
        '''
        offset = 0
        data_length = len(data)
        self.logger.debug('data_length: %d' % data_length)
        # parse multiple msgs in data
        while data_length - offset >= 8:
            ofp_type = ord(data[offset + 1])

            # ofp version checking
            if ord(data[offset]) != of.OFP_VERSION:
                if ofp_type == of.OFPT_HELLO:
                    self.logger.info(
                        'ofp ver err: the connection to controller is closed by scl_proxy, '
                        'conn_id: %d', conn.conn_id)
                    self.clean_connection(conn.sock, conn.conn_id)
                else:
                    self.logger.warn(
                            'Bad OpenFlow version (0x%02x)' % ord(data[offset]))
                    break

            # ofp msg length checking
            msg_length = ord(data[offset + 2]) << 8 | ord(data[offset + 3])
            if msg_length is 0 or data_length - offset < msg_length:
                self.logger.error('msg_length: %d, buffer error' % msg_length)
                break
            self.logger.debug('ofp_type: %d, msg_length: %d' % (ofp_type, msg_length))

            # unpack msg according to ofp_type
            new_offset, msg = unpackers[ofp_type](data, offset)
            assert new_offset - offset == msg_length
            offset = new_offset

            # handle ofp msg
            try:
                h = handlers[ofp_type]
                h(self, conn, msg)
            except Exception, e:
                self.logger.error(
                        "Exception while handling OpenFlow %s msg, err: %s" % (ofp_type, e))

    def wait(self, selector):
        self.adjust_outputs()
        selector.wait(self.inputs, self.outputs)

    def run(self, lists):
        for s in self.tcp_conns.sock2conn.keys():
            # socket is writeable
            if s in lists[1]:
                conn = self.tcp_conns.sock2conn[s]
                # conn and of channels are both up
                if conn.connectted:
                    self.logger.debug('send msg to controller')
                    next_msg = self.streams.upstreams[conn.conn_id].get_nowait()
                    conn.send(next_msg)
                # connection is on going or failed
                else:
                    # check the connecting socket
                    connectted, err = conn.isconnectted()
                    if connectted:
                        self.logger.info(
                            'connection to controller successful, '
                            'conn_id: %d' % conn.conn_id)
                        # wait the controller to send ofp_hello msg first
                        # start of channel passively
                        self.inputs.append(s)
                    elif not connectted and err is not errno.EINPROGRESS:
                        self.logger.error(
                            'connecting to controller fails, errno %d' % err)
                        self.clean_connection(s, conn.conn_id)
            # socket is readable
            if s in lists[0]:
                self.logger.debug('receive msg from controller')
                conn = self.tcp_conns.sock2conn[s]
                try:
                    data = conn.recv(RECV_BUF_SIZE)
                    if data:
                        self.handle_of_msg(conn, data)
                    else:
                        self.logger.info(
                            'connection closed by controller, conn_id: %d' % conn.conn_id)
                        self.clean_connection(s, conn.conn_id)
                except socket.error, e:
                    logger.error('error in connection to controller: %s' % e)
            # check timer, time up per second
            # send echo request to controller every second
            if self.timer.time_up:
                conn = self.tcp_conns.sock2conn[s]
                if conn.connectted and self.streams.ofp_connected[conn.conn_id]:
                    self.logger.debug('periodically send ofp_echo_request msg')
                    if self.streams.ofp_echo_times[conn.conn_id] >= ECHO_TIMEOUT:
                        self.logger.error(
                            'echo timeout: the connection to controller is closed by scl_proxy, '
                            'conn_id: %d' % conn.conn_id)
                        self.clean_connection(conn.sock, conn.conn_id)
                    else:
                        echo_rqst = of.ofp_echo_request()
                        # FIXME: may receive disordered xid, temp method: set xid 0
                        echo_rqst.xid = 0
                        conn.send(echo_rqst.pack())
                        self.streams.ofp_echo_ids[conn.conn_id] = echo_rqst.xid
                        self.streams.ofp_echo_times[conn.conn_id] += 1


class Scl2Scl(object):
    '''
    channel from scl on controller side to scl on switch side
    one udp socket as a multicast listener
    '''
    def __init__(
            self, scl_proxy_mcast_grp, scl_proxy_mcast_port, scl_proxy_intf,
            scl_agent_mcast_grp, scl_agent_mcast_port, scl2ctrl, timer, streams, logger):
        self.udp_mcast = UdpMcastListener(
                scl_proxy_mcast_grp, scl_proxy_mcast_port, scl_proxy_intf,
                scl_agent_mcast_grp, scl_agent_mcast_port)
        self.udp_mcast.open()
        self.scl2ctrl = scl2ctrl
        self.timer = timer
        self.streams = streams
        self.logger = logger

    def handle_of_msg(self, conn_id, seq, data):
        if conn_id not in self.streams.last_of_seqs:
            self.logger.warn(
                    'receive ofp_msg from an unknown switch, '
                    'the connection needs to be set up first')
        else:
            if self.streams.last_of_seqs[conn_id] >= seq:
                self.logger.warn('receive disordered msg from scl_agent')
            else:
                self.streams.last_of_seqs[conn_id] = seq
                self.logger.debug('receive SCLT_OF')
                self.streams.upstreams[conn_id].put(data)

    def handle_link_notify_msg(self, conn_id, seq, data):
        switch = id2str(conn_id)
        if switch not in self.streams.link_log.switches():
            self.logger.info(
                    'receive link msg of a new switch by scl_agent, '
                    'set up a new connection from proxy to controller')
            self.scl2ctrl.open(conn_id, seq)
        # parse scl link state msg
        link, port_no, state, version = scl.link_state_unpack(data)
        link = str(link) + '-' + str(port_no)
        ret = self.streams.link_log.update(switch, link, version, state)
        if ret:
            self.streams.upcall_link_status(ret[0], ret[1], ret[2])
        self.logger.info(
                '%s, %s, version: %d, state: %s' % (
                    switch, link, version, state))

    def process_data(self, conn_id, type, seq, data):
        '''
        process data received from scl_agent
        classify type, check sequence num, msg enqueue
        '''
        if type is scl.SCLT_OF:
            self.handle_of_msg(conn_id, seq, data)
        elif type is scl.SCLT_LINK_NOTIFY:
            self.handle_link_notify_msg(conn_id, seq, data)

    def wait(self, selector):
        if not self.streams.downstreams_empty():
            selector.wait([self.udp_mcast.sock], [self.udp_mcast.sock])
        else:
            selector.wait([self.udp_mcast.sock], [])

    def run(self, lists):
        # socket is writeable
        if self.udp_mcast.sock in lists[1]:
            for conn_id in self.streams.downstreams:
                if not self.streams.downstreams[conn_id].empty():
                    self.logger.debug(
                        'send a msg to scl_agent %s' % id2str(conn_id))
                    next_msg = self.streams.downstreams[conn_id].get_nowait()
                    self.udp_mcast.send_to_id(next_msg, conn_id)

        # socket is readable
        if self.udp_mcast.sock in lists[0]:
            data, conn_id = self.udp_mcast.recvfrom(RECV_BUF_SIZE)
            self.logger.debug('receive msgs from scl_agent %s' % id2str(conn_id))
            if data:
                type, seq, data = scl.parseheader(data)
                self.process_data(conn_id, type, seq, data)

        # check timer
        # (count + 1) % 3 per second
        # send link state request each three seconds
        if self.timer.time_up and self.timer.count == 1:
            # NOTE: switches upcall periodically
            pass
            #self.logger.debug('periodically broadcast link state rqst msg')
            #self.udp_mcast.multicast(scl.addheader('', scl.SCLT_LINK_RQST), dst=True)
