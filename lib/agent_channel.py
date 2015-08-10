import Queue
import socket
from const import RECV_BUF_SIZE
from socket_utils import *
from lib.ovsdb_utils import OvsdbConn
from lib.libopenflow_01 import ofp_port_status
from lib.libopenflow_01 import ofp_features_reply
from lib.libopenflow_01 import ofp_error
import scl_protocol as scl


class Streams(object):
    def __init__(self):
        self.upstream = Queue.Queue()
        self.downstream = Queue.Queue()
        self.link_events = scl.SwitchLinkEvents()
        self.last_of_seq = -1
        self.datapath_id = None


class Scl2Sw(object):
    def __init__(self, scl_agent_serv_host, scl_agent_serv_port, streams, logger):
        self.tcp_serv = TcpListen(scl_agent_serv_host, scl_agent_serv_port)
        self.tcp_serv.open()
        self.tcp_client = None
        self.streams = streams
        self.logger = logger

    def handle_port_status(self, data):
        port_status = ofp_port_status()
        port_status.unpack(data)
        self.logger.info(
            'openflow msg %s %d' % (
                port_status.desc.name, port_status.desc.state))
        msg = self.streams.link_events.update(
            port_status.desc.name, port_status.desc.state)
        self.streams.upstream.put(scl.addheader(msg, scl.SCLT_LINK_NOTIFY))

    def handle_of_msg(self, data):
        '''
        parse openflow messages
        put data into upstream
        '''
        self.streams.upstream.put(scl.addheader(data, scl.SCLT_OF))
        offset = 0
        data_length = len(data)
        self.logger.debug('data_length: %d' % data_length)
        # parse multiple of msgs in one data
        while data_length - offset >= 8:
            of_type = ord(data[offset + 1])
            msg_length = ord(data[offset + 2]) << 8 | ord(data[offset + 3])
            if msg_length is 0:
                self.logger.error('msg_length: %d, buffer error' % msg_length)
                break
            self.logger.debug('of_type: %d, msg_length: %d' % (of_type, msg_length))
            if data_length - offset < msg_length:
                break

            # OFPT_PORT_STATUS
            if of_type == 12:
                self.handle_port_status(data[offset: offset + msg_length])
            # OFPT_FEATURES_REPLY
            elif of_type == 6:
                features_reply = ofp_features_reply()
                features_reply.unpack(data[offset: offset + msg_length])
                self.streams.datapath_id =\
                    hex(features_reply.datapath_id)[2:].zfill(16)
            # OFPT_ERROR
            elif of_type == 1:
                error = ofp_error()
                error.unpack(data[offset: offset + msg_length])
                self.logger.debug(
                        'ofp_error, type: %d, code: %d, data: %s',
                        error.type, error.code, error.data)

            offset = offset + msg_length

    def client_close(self):
        self.tcp_client = None
        # send connection close msg to controller
        self.streams.downstream.queue.clear()
        self.streams.upstream.put(scl.addheader('', scl.SCLT_CLOSE))
        self.streams.last_of_seq = -1

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
            self.logger.debug(
                'send SCLT_HELLO msg to scl_proxy to '
                'set up connection between scl_proxy and controller')
            self.streams.upstream.put(scl.addheader('', scl.SCLT_HELLO))

        # socket is readable
        if self.tcp_client in lists[0]:
            self.logger.debug('receive msg from switch')
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
    def __init__(self, scl_proxy_mcast_grp, scl_proxy_mcast_port, streams, logger):
        self.udp_conn = UdpConn(scl_proxy_mcast_grp, scl_proxy_mcast_port)
        self.udp_conn.open()
        self.streams = streams
        self.logger = logger

    def hand_link_request(self):
        for msg in self.streams.link_events.current_events():
            self.streams.upstream.put(scl.addheader(msg, scl.SCLT_LINK_NOTIFY))

    def handle_of_msg(self, data):
        '''
        parse of openflow messages
        put data into downstream
        '''
        self.streams.downstream.put(data)
        offset = 0
        data_length = len(data)
        self.logger.debug('data_length: %d' % data_length)
        # parse multiple of msgs in one data
        while data_length - offset >= 8:
            of_type = ord(data[offset + 1])
            msg_length = ord(data[offset + 2]) << 8 | ord(data[offset + 3])
            if msg_length is 0:
                self.logger.error('msg_length: %d, buffer error' % msg_length)
                break
            self.logger.debug('of_type: %d, msg_length: %d' % (of_type, msg_length))
            if data_length - offset < msg_length:
                break
            offset = offset + msg_length

    def wait(self, selector):
        if not self.streams.upstream.empty():
            selector.wait([self.udp_conn.sock], [self.udp_conn.sock])
        else:
            selector.wait([self.udp_conn.sock], [])

    def run(self, lists):
        # socket is readable
        if self.udp_conn.sock in lists[0]:
            data, addr = self.udp_conn.sock.recvfrom(RECV_BUF_SIZE)
            if data:
                # deal with commands from scl proxies
                type, seq, data = scl.parseheader(data)
                if type is scl.SCLT_OF and seq > self.streams.last_of_seq:
                    self.streams.last_of_seq = seq
                    self.logger.debug('receive of msg from scl_proxy %s', addr[0])
                    self.handle_of_msg(data)
                elif type is scl.SCLT_LINK_RQST:
                    self.logger.debug('receive link rqst msg from scl_proxy %s', addr[0])
                    self.hand_link_request()

        # socket is writeable
        if self.udp_conn.sock in lists[1]:
            self.logger.debug('broadcast msg to scl_proxy')
            next_msg = self.streams.upstream.get_nowait()
            self.udp_conn.sock.sendto(next_msg, self.udp_conn.dst_addr)
