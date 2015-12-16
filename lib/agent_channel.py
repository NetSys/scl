import Queue
import socket
from conf.const import RECV_BUF_SIZE
from socket_utils import *
from ovsdb_utils import OvsdbConn
import libopenflow_01 as of
import scl_protocol as scl


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

def handle_HELLO(scl2sw, msg):
    hello = of.ofp_hello()
    scl2sw.streams.downstream.put(hello.pack())
    msg = of.ofp_features_request()
    scl2sw.streams.downstream.put(msg.pack())

def handle_ECHO_REPLY(scl2sw, msg):
    pass

def handle_ECHO_REQUEST(scl2sw, msg):
    if scl2sw.streams.sw_connected:
        reply = msg
        reply.header_type = of.OFPT_ECHO_REPLY
        scl2sw.streams.downstream.put(reply.pack())

def handle_FEATURES_REPLY(scl2sw, msg):
    scl2sw.streams.sw_features = msg
    scl2sw.streams.dpid = hex(msg.datapath_id)[2:].zfill(16)
    for port in msg.ports:
        # port name like s001 is internal port, pass it
        if len(port.name.split('-')) is 1:
            continue
        scl2sw.logger.info('port_status: %s %d' % (port.name, port.state))
        link_msg = scl2sw.streams.link_events.update(
                port.name, port.port_no, port.state)
        scl2sw.streams.upstream.put(scl.addheader(link_msg, scl.SCLT_LINK_NOTIFY))

    set_config = of.ofp_set_config()
    barrier = of.ofp_barrier_request()
    scl2sw.streams.barrier_xid = barrier.xid
    scl2sw.streams.downstream.put(set_config.pack())
    scl2sw.streams.downstream.put(barrier.pack())

def handle_PORT_STATUS(scl2sw, msg):
    if msg.reason == of.OFPPR_DELETE:
        # TODO: scl.SCLT_LINK_DELETE?
        pass
    elif len(msg.desc.name.split('-')) is 1:
        # port name like s001 is internal port, pass it
        pass
    else:
        scl2sw.logger.info('port_status: %s %d' % (msg.desc.name, msg.desc.state))
        link_msg = scl2sw.streams.link_events.update(
                msg.desc.name, msg.desc.port_no, msg.desc.state)
        scl2sw.streams.upstream.put(scl.addheader(link_msg, scl.SCLT_LINK_NOTIFY))

def handle_PACKET_IN(scl2sw, msg):
    scl2sw.streams.upstream.put(scl.addheader(msg.pack(), scl.SCLT_OF))

def handle_ERROR_MSG(scl2sw, msg):
    scl2sw.logger.info('ofp_error: %s' % msg.show())

    # deal with barrier corner case
    if msg.xid != scl2sw.streams.barrier_xid: return
    if msg.ofp.type != of.OFPET_BAD_REQUEST: return
    if msg.ofp.code != of.OFPBRC_BAD_TYPE: return
    # Okay, so this is probably an HP switch that doesn't support barriers
    # (ugh).  We'll just assume that things are okay.
    scl2sw.logger.info('connection handshake successes')
    scl2sw.streams.sw_connected = True

def handle_BARRIER(scl2sw, msg):
    if msg.xid != scl2sw.streams.barrier_xid:
        scl2sw.logger.info('connection to switch closed by scl_agent')
        scl2sw.tcp_client.close()
        scl2sw.client_close()
    else:
        scl2sw.logger.info('connection handshake successes')
        scl2sw.streams.sw_connected = True

# A list, where the index is an OFPT, and the value is a function to
# call for that type
# This is generated automatically based on handlerMap
handlers = []

# Message handlers
handlerMap = {
    of.OFPT_HELLO : handle_HELLO,
    of.OFPT_ECHO_REQUEST : handle_ECHO_REQUEST,
    of.OFPT_ECHO_REPLY : handle_ECHO_REPLY,
    of.OFPT_PACKET_IN : handle_PACKET_IN,
    of.OFPT_FEATURES_REPLY : handle_FEATURES_REPLY,
    of.OFPT_PORT_STATUS : handle_PORT_STATUS,
    of.OFPT_ERROR : handle_ERROR_MSG,
    of.OFPT_BARRIER_REPLY : handle_BARRIER,
}

def _set_handlers ():
    handlers.extend([None] * (1 + sorted(handlerMap.keys(),reverse=True)[0]))
    for h in handlerMap:
        handlers[h] = handlerMap[h]
#----------------------------------------------------------------------------#


class Streams(object):
    def __init__(self, logger):
        self.upstream = Queue.Queue()
        self.downstream = Queue.Queue()
        self.link_events = scl.SwitchLinkEvents()
        self.flow_table = scl.FlowTable(logger)
        self.scl2scl_buff = ''
        self.sw_ofp_buff = ''
        self.sw_connected = False
        self.last_of_seq = -1
        self.sw_features = None
        self.datapath_id = None
        self.barrier_xid = 0


class Scl2Sw(object):
    def __init__(self, scl_agent_serv_host, scl_agent_serv_port, streams, logger):
        self.tcp_serv = TcpListen(scl_agent_serv_host, scl_agent_serv_port)
        self.tcp_serv.open()
        self.tcp_client = None
        self.streams = streams
        self.logger = logger
        _set_handlers()

    def handle_of_msg(self, data):
        '''
        handshake
        port_status
        '''
        offset = 0
        data_length = len(data)
        tmp_buff = self.streams.sw_ofp_buff
        tmp_buff += data
        buff_length = len(data)
        self.logger.debug(
                'data_length: %d, buff_length: %d.' % (data_length, buff_length))
        # parse multiple msgs in buff
        while buff_length - offset >= 8:
            ofp_type = ord(tmp_buff[offset + 1])

            # ofp msg length checking
            # assume that 2nd and 3rd bytes are for length
            msg_length = ord(tmp_buff[offset + 2]) << 8 | ord(tmp_buff[offset + 3])
            if buff_length - offset < msg_length:
                break

            # ofp version checking
            if ord(tmp_buff[offset]) != of.OFP_VERSION:
                if ofp_type == of.OFPT_HELLO:
                    pass    # wait for switches to be timeout
                else:
                    self.logger.warn(
                            'Bad OpenFlow version (0x%02x)' % ord(tmp_buff[offset]))
                    offset = offset + msg_length
                    continue

            self.logger.debug('ofp_type: %d, msg_length: %d' % (ofp_type, msg_length))

            # unpack msg according to ofp_type
            new_offset, msg = unpackers[ofp_type](tmp_buff, offset)
            assert new_offset - offset == msg_length
            offset = new_offset

            # handle ofp msg
            #try:
            h = handlers[ofp_type]
            h(self, msg)
            #except Exception, e:
            #    self.logger.error(
            #            "Exception while handling OpenFlow %s msg, err: %s" % (ofp_type, e))

        # save the uncomplete buffer
        self.streams.sw_ofp_buff = tmp_buff[offset:]

    def client_close(self):
        self.tcp_client = None
        self.streams.downstream.queue.clear()
        self.streams.last_of_seq = -1
        self.streams.sw_ofp_buff = ''
        self.streams.sw_connected = False
        self.streams.sw_features = None
        self.streams.barrier_xid = 0
        self.streams.datapath_id = None
        self.streams.flow_table.reset()

    def wait(self, selector):
        if not self.tcp_client:
            selector.wait([self.tcp_serv.sock], [])
        elif self.streams.downstream.empty():
            selector.wait([self.tcp_serv.sock, self.tcp_client], [])
        else:
            selector.wait([self.tcp_serv.sock, self.tcp_client], [self.tcp_client])

    def run(self, lists):
        # receive connection from the switch
        if self.tcp_serv.sock in lists[0]:
            self.logger.info('new connection from the switch')
            self.tcp_client, addr = self.tcp_serv.sock.accept()
            self.tcp_client.setblocking(0)      # non-blocking

        # socket is readable
        if self.tcp_client in lists[0]:
            self.logger.debug('receive msgs from the switch')
            try:
                data = self.tcp_client.recv(RECV_BUF_SIZE)
                if data:
                    # deal with messages from the switch
                    # add scl header, put data into upstream
                    self.handle_of_msg(data)
                else:
                    self.logger.info(
                        'connection to switch closed by the switch')
                    self.client_close()
            except socket.error, e:
                self.logger.error(
                    'connection to switch closed abnormally, error %s' % e)
                self.client_close()

        # socket is writeable
        if self.tcp_client in lists[1]:
            self.logger.debug('send msg to switch')
            if not self.streams.downstream.empty():
                next_msg = self.streams.downstream.get_nowait()
                self.tcp_client.send(next_msg)


class Scl2Scl(object):
    def __init__(self, scl_agent_mcast_grp, scl_agent_mcast_port, scl_agent_intf,
            scl_proxy_mcast_grp, scl_proxy_mcast_port, timer, streams, logger):
        self.udp_mcast = UdpMcastListener(
                scl_agent_mcast_grp, scl_agent_mcast_port, scl_agent_intf,
                scl_proxy_mcast_grp, scl_proxy_mcast_port)
        self.udp_mcast.open()
        self.timer = timer
        self.streams = streams
        self.logger = logger

    def handle_flow_table_request(self):
        for msg in self.streams.flow_table.current_flow_entries():
            self.streams.upstream.put(scl.addheader(msg, scl.SCLT_FLOW_TABLE_NOTIFY))

    def handle_link_request(self):
        for msg in self.streams.link_events.current_events():
            self.streams.upstream.put(scl.addheader(msg, scl.SCLT_LINK_NOTIFY))

    def handle_of_msg(self, data):
        '''
        parse ofp_flow_mod messages
        put data into downstream
        '''
        offset = 0
        data_length = len(data)
        tmp_buff = self.streams.scl2scl_buff
        tmp_buff += data
        buff_length = len(data)
        self.logger.debug(
                'data_length: %d, buff_length: %d.' % (data_length, buff_length))
        # parse multiple msgs in buff
        while buff_length - offset >= 8:
            ofp_type = ord(tmp_buff[offset + 1])

            # ofp msg length checking
            # assume that 2nd and 3rd bytes are for length
            msg_length = ord(tmp_buff[offset + 2]) << 8 | ord(tmp_buff[offset + 3])
            if buff_length - offset < msg_length:
                break

            # ofp version checking
            if ord(tmp_buff[offset]) != of.OFP_VERSION:
                self.logger.warn(
                        'Bad OpenFlow version (0x%02x)' % ord(tmp_buff[offset]))
                offset = offset + msg_length
                continue

            self.logger.debug('ofp_type: %d, msg_length: %d' % (ofp_type, msg_length))

            self.streams.downstream.put(tmp_buff[offset: offset + msg_length])

            # handle_FLOW_MOD
            if ofp_type == of.OFPT_FLOW_MOD:
                new_offset, msg = unpackers[ofp_type](tmp_buff, offset)
                assert new_offset - offset == msg_length
                offset = new_offset
                self.streams.flow_table.update(msg)
            else:
                offset += msg_length

        # save the uncomplete buffer
        self.streams.scl2scl_buff = tmp_buff[offset:]

    def wait(self, selector):
        if not self.streams.upstream.empty():
            selector.wait([self.udp_mcast.sock], [self.udp_mcast.sock])
        else:
            selector.wait([self.udp_mcast.sock], [])

    def run(self, lists):
        # socket is readable
        if self.udp_mcast.sock in lists[0]:
            self.logger.debug('udp_mcast listener socket is readable')
            data, addr = self.udp_mcast.sock.recvfrom(RECV_BUF_SIZE)
            if data:
                self.logger.debug('udp_mcast listener received msg')
                # deal with commands from scl proxies
                scl_type, seq, data = scl.parseheader(data)
                if scl_type is scl.SCLT_OF and not self.streams.sw_connected:
                    self.logger.error('receive ofp_msg from scl_proxy ',
                            addr[0], 'while connection to switch closed')
                elif scl_type is scl.SCLT_OF and self.streams.sw_connected:
                    self.logger.debug('receive ofp_msg from scl_proxy %s' % addr[0])
                    self.handle_of_msg(data)
                elif scl_type is scl.SCLT_LINK_RQST:
                    self.logger.debug('receive sclt_link_rqst msg from scl_proxy %s' % addr[0])
                    self.handle_link_request()
                elif scl_type is scl.SCLT_FLOW_TABLE_RQST:
                    self.logger.debug('receive sclt_flow_table_rqst msg from scl_proxy %s' % addr[0])
                    self.handle_flow_table_request()

        # socket is writeable
        if self.udp_mcast.sock in lists[1]:
            self.logger.debug('broadcast msg to scl_proxy')
            next_msg = self.streams.upstream.get_nowait()
            self.udp_mcast.multicast(next_msg, dst=True)
