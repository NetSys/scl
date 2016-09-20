import Queue
import socket
import time
import errno
from collections import defaultdict
from conf.const import RECV_BUF_SIZE
from socket_utils import *
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
        if port.port_no == 65534:
            # internal port, pass it
            continue
        scl2sw.logger.info('port_status: %s %d' % (port.name, port.state))
        link_msg = scl2sw.streams.link_events.update(
                port.name, port.port_no, port.state)
        scl2sw.streams.upstream.put([link_msg, scl.SCLT_LINK_NOTIFY])

    set_config = of.ofp_set_config()
    barrier = of.ofp_barrier_request()
    scl2sw.streams.barrier_xid = barrier.xid
    scl2sw.streams.downstream.put(set_config.pack())
    scl2sw.streams.downstream.put(barrier.pack())

def handle_PORT_STATUS(scl2sw, msg):
    if msg.reason == of.OFPPR_DELETE:
        pass
    elif msg.desc.port_no == 65534:
        # internal port, pass it
        pass
    else:
        scl2sw.logger.info('port_status: %s %d' % (msg.desc.name, msg.desc.state))
        link_msg = scl2sw.streams.link_events.update(
                msg.desc.name, msg.desc.port_no, msg.desc.state)
        scl2sw.streams.upstream.put([link_msg, scl.SCLT_LINK_NOTIFY])

def handle_PACKET_IN(scl2sw, msg):
    #scl2sw.streams.upstream.put([msg.pack(), scl.SCLT_OF_AGENT])
    pass

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

def handle_STATS_REPLY(scl2sw, msg):
    # send flow stats reply back to scl proxies
    scl2sw.logger.debug('handle_STATS_REPLY')
    scl2sw.logger.debug('stats reply packet,  %s' % msg.show())
    if msg.type != of.OFPST_FLOW:
        return

    if len(scl2sw.streams.flow_stats_buff) != 0:
        if msg.xid == scl2sw.streams.flow_stats_buff[0].xid:
            scl2sw.streams.flow_stats_buff.append(msg)
        else:
            scl2sw.logger.error(
                    'continuous stats failed new xid %d, excepted xid %d' % (
                        msg.xid, scl2sw.streams.flow_stats_buff[0].xid))
    else:
        scl2sw.streams.flow_stats_buff = [msg]

    if msg.is_last_reply:
        t = time.time()
        sec = int(t)
        nsec = int((t - sec) * 1000000000)
        (addr, seq) = scl2sw.streams.flow_stats_seq_q.get()
        assert seq == scl2sw.streams.flow_stats_buff[0].xid
        for msg in scl2sw.streams.flow_stats_buff:
            ofp_flow_stats_rply_msg = scl.flow_stats_rply_pack(
                    addr, seq, sec, nsec, msg.pack())
            scl2sw.streams.upstream.put(
                    [ofp_flow_stats_rply_msg, scl.SCLT_FLOW_STATS_REPLY])
        scl2sw.streams.flow_stats_buff = []

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
    of.OFPT_STATS_REPLY : handle_STATS_REPLY,
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
        self.scl2scl_buffs = defaultdict(lambda: '')  # conn_id: data from different controllers
        self.sw_ofp_buff = ''
        self.flow_stats_seq_q = Queue.Queue()
        self.flow_stats_buff = []
        self.sw_connected = False
        self.sw_features = None
        self.datapath_id = None
        self.barrier_xid = 0

    def reset(self):
        self.downstream.queue.clear()
        self.flow_table.reset()
        self.flow_stats_seq_q.queue.clear()
        self.flow_stats_buff = []
        self.sw_ofp_buff = ''
        self.sw_connected = False
        self.sw_features = None
        self.datapath_id = None
        self.barrier_xid = 0

    def upstream_enqueue(self, msgs):
        for msg in msgs:
            self.upstream.put(msg)


class Scl2Sw(object):
    def __init__(self, scl_agent_srvr_host, scl_agent_srvr_port, streams, logger):
        self.tcp_srvr = TcpListener(scl_agent_srvr_host, scl_agent_srvr_port)
        self.tcp_srvr.open()
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
        buff_length = len(tmp_buff)
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
            try:
                h = handlers[ofp_type]
                h(self, msg)
            except Exception, e:
                self.logger.error(
                        "Exception while handling OpenFlow %s msg, err: %s" % (ofp_type, e))

        # save the uncomplete buffer
        self.streams.sw_ofp_buff = tmp_buff[offset:]

    def client_close(self):
        self.tcp_client = None
        self.streams.reset()

    def wait(self, selector):
        if not self.tcp_client:
            selector.wait([self.tcp_srvr.sock], [])
        elif self.streams.downstream.empty():
            selector.wait([self.tcp_srvr.sock, self.tcp_client], [])
        else:
            selector.wait([self.tcp_srvr.sock, self.tcp_client], [self.tcp_client])

    def run(self, lists):
        # receive connection from the switch
        if self.tcp_srvr.sock in lists[0]:
            self.logger.info('new connection from the switch')
            self.tcp_client, addr = self.tcp_srvr.sock.accept()
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
    def __init__(self, streams, logger, scl_agent_intf):
        self.streams = streams
        self.logger = logger
        self.addr = scl_agent_intf
        scl.my_addr = scl_agent_intf
        scl.my_type = scl.SCL_AGENT

    def handle_flow_table_request(self):
        for msg in self.streams.flow_table.current_flow_entries():
            self.streams.upstream.put([msg, scl.SCLT_FLOW_TABLE_NOTIFY])

    def handle_link_request(self):
        for msg in self.streams.link_events.current_events():
            self.streams.upstream.put([msg, scl.SCLT_LINK_NOTIFY])

    def handle_flow_stats_request(self, data):
        addr, seq, ofp_stats_rqst_msg = scl.flow_stats_rqst_unpack(data)
        self.streams.flow_stats_seq_q.put((addr, seq))
        self.streams.downstream.put(ofp_stats_rqst_msg)

    def handle_of_msg(self, conn_id, data):
        '''
        parse ofp_flow_mod messages
        put data into downstream
        '''
        offset = 0
        data_length = len(data)
        tmp_buff = self.streams.scl2scl_buffs[conn_id]
        tmp_buff += data
        buff_length = len(tmp_buff)
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
        self.streams.scl2scl_buffs[conn_id] = tmp_buff[offset:]

    def process_msg(self, ctrl_addr, sclt, msg):
        if sclt is scl.SCLT_OF_PROXY and not self.streams.sw_connected:
            self.logger.error('receive ofp_msg from scl_proxy %s ' % ctrl_addr,
                    'while connection to switch closed')
        elif sclt is scl.SCLT_OF_PROXY and self.streams.sw_connected:
            self.logger.debug('receive ofp_msg from scl_proxy %s' % ctrl_addr)
            self.handle_of_msg(str2id(ctrl_addr), msg)
        elif sclt is scl.SCLT_LINK_RQST:
            self.logger.debug('receive sclt_link_rqst msg from scl_proxy %s' % ctrl_addr)
            self.handle_link_request()
        elif sclt is scl.SCLT_FLOW_TABLE_RQST:
            self.logger.debug('receive sclt_flow_table_rqst msg from scl_proxy %s' % ctrl_addr)
            self.handle_flow_table_request()
        elif sclt is scl.SCLT_FLOW_STATS_RQST:
            self.logger.debug('receive sclt_flow_stats_rqst msg from scl_proxy %s' % ctrl_addr)
            self.handle_flow_stats_request(msg)


class Scl2SclUdp(Scl2Scl):
    def __init__(
            self, streams, logger, scl_agent_intf, scl_agent_port, scl_proxy_port):
        super(Scl2SclUdp, self).__init__(streams, logger, scl_agent_intf)
        self.udp_flood = UdpFloodListener('', scl_agent_port, scl_proxy_port)

    def send_raw(self, msg, sclt, dst_addr):
        self.udp_flood.send(scl.scl_udp_pack(msg, sclt, self.addr, dst_addr))

    def send_data(self, data):
        self.udp_flood.send(data)

    def wait(self, selector):
        if not self.streams.upstream.empty():
            selector.wait([self.udp_flood.sock], [self.udp_flood.sock])
        else:
            selector.wait([self.udp_flood.sock], [])

    def run(self, lists):
        # socket is readable
        if self.udp_flood.sock in lists[0]:
            self.logger.debug('udp flood listener socket is readable')
            data = self.udp_flood.recv(RECV_BUF_SIZE)
            if data:
                self.logger.debug('udp flood listener received msg')
                # deal with commands from scl proxies
                flood, sclt, conn_id, msg = scl.scl_udp_unpack(data)
                if flood:
                    self.send_data(data)
                if msg:
                    self.process_msg(id2str(conn_id), sclt, msg)

        # socket is writeable
        if self.udp_flood.sock in lists[1]:
            self.logger.debug('broadcast msg to scl_proxy')
            msg, sclt = self.streams.upstream.get_nowait()
            self.send_raw(msg, sclt, scl.ALL_CTRL_ADDR)


class Scl2SclTcp(Scl2Scl):
    def __init__(
            self, streams, logger, scl_agent_intf, proxy_list, scl_proxy_port, timer):
        super(Scl2SclTcp, self).__init__(streams, logger, scl_agent_intf)
        self.timer = timer
        self.tcp_conns = TcpConnsOne2Multi(proxy_list, scl_proxy_port)
        self.dst_intfs = proxy_list
        self.inputs = []
        self.outputs = []
        self.waitings = []
        for intf in self.dst_intfs:
            self.open(intf)

    def open(self, intf):
        ret, err = self.tcp_conns.open(intf)
        if ret:
            self.logger.info(
                'successfully connect to scl_proxy, dst: %s' % intf)
            self.inputs.append(self.tcp_conns.intf2conn[intf].sock)
            self.outputs.append(self.tcp_conns.intf2conn[intf].sock)
        elif err.errno is errno.EINPROGRESS:
            self.logger.info(
                'connecting to scl_proxy, dst: %s' % intf)
            self.waitings.append(self.tcp_conns.intf2conn[intf].sock)
        else:
            self.logger.error(
                    'connect to scl_proxy fails, errno %d, dst: %s' % (
                        err.errno, intf))
            self.tcp_conns.close(intf)

    def clean_connection(self, intf=None, sock=None):
        if not intf and not sock:
            return
        elif not intf:
            intf = self.tcp_conns.sock2conn[sock].conn_id
        elif not sock:
            sock = self.tcp_conns.intf2conn[intf].sock
        self.logger.debug('clean connection to proxy %s' % intf)
        if sock in self.inputs:
            self.inputs.remove(sock)
        if sock in self.outputs:
            self.outputs.remove(sock)
        if sock in self.waitings:
            self.waitings.remove(sock)
        self.tcp_conns.close(intf)

    def send_raw_to_one(self, msg, sclt, sock):
        try:
            sock.send(scl.scl_tcp_pack(msg, sclt, self.addr, scl.ALL_CTRL_ADDR))
        except socket.error, e:
            conn = self.tcp_conns.sock2conn[sock]
            self.logger.error('error in connection to scl_proxy %s, e: %s' % (conn.conn_id, e))
            self.clean_connection(conn.conn_id, sock)

    def wait(self, selector):
        '''
        when stream is empty, remove the corresponding socket from outputs.
        if writeable socket is put into outputs directly, select will be called
        more frequentlty and the cpu usage may be 100%.
        '''
        if not self.streams.upstream.empty():
            selector.wait(self.inputs, self.outputs + self.waitings)
        else:
            selector.wait(self.inputs, self.waitings)

    def run(self, lists):
        # check the connecting socket
        for s in self.waitings:
            conn = self.tcp_conns.sock2conn[s]
            if conn.connectted:
                self.logger.info(
                    'successfully connect to scl_proxy, dst: %s' % conn.conn_id)
                self.waitings.remove(s)
                self.outputs.append(s)
                self.inputs.append(s)
            else:
                connectted, err = conn.isconnectted()
                if connectted:
                    self.logger.info(
                        'successfully connect to scl_proxy, dst: %s' % conn.conn_id)
                    self.waitings.remove(s)
                    self.outputs.append(s)
                    self.inputs.append(s)
                elif err is not errno.EINPROGRESS:
                    self.logger.error(
                            'connect to scl_proxy fails, errno %d, dst: %s' % (
                                err, conn.conn_id))
                    self.clean_connection(conn.conn_id, s)
                else:
                    self.logger.info(
                            'connecting to scl_proxy, dst: %s' % conn.conn_id)
        # writeable
        if not self.streams.upstream.empty():
            msg, sclt = self.streams.upstream.get_nowait()
            sent = False
            for s in self.outputs:
                if s in lists[1]:
                    self.logger.debug("... sendto addr %s", self.tcp_conns.sock2conn[s].conn_id)
                    self.send_raw_to_one(msg, sclt, s)
                    sent = True
            if not sent:
                self.streams.upstream.put([msg, sclt])
        # readable
        for s in self.inputs:
            if s in lists[0]:
                intf = self.tcp_conns.sock2conn[s].conn_id
                try:
                    data = s.recv(RECV_BUF_SIZE)
                    if data:
                        self.logger.debug('tcp_conns received msg from scl_proxy %s' % intf)
                        # deal with commands from scl proxies
                        ret = scl.scl_tcp_unpack(data, intf)
                        for flood, sclt, msg in ret:
                            if not msg:
                                self.logger.debug('... received, but msg is None')
                                continue
                            self.logger.debug('....received, msg is not None')
                            self.process_msg(intf, sclt, msg)
                    else:
                        self.logger.info(
                                'connection closed by scl_proxy %s' % intf)
                        self.clean_connection(intf, s)
                except socket.error, e:
                    self.logger.error('error in connection to scl_proxy %s, e: %s' % (intf, e))
                    self.clean_connection(intf, s)
        # reconnect failed socket
        if self.timer.time_up:
            for intf in self.dst_intfs:
                if not self.tcp_conns.intf2conn[intf]:
                    self.open(intf)
