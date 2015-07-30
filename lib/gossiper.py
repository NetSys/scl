import socket
import random
import json
from const import RECV_BUF_SIZE


def byteify(input):
    '''
    convert unicode from json.loads to utf-8
    '''
    if isinstance(input, dict):
        return {byteify(key): byteify(value) for key, value in input.iteritems()}
    elif isinstance(input, list):
        return [byteify(element) for element in input]
    elif isinstance(input, unicode):
        return input.encode('utf-8')
    else:
        return input


class Gossiper(object):
    def __init__(self, host_id, peer_lists, timer, streams, logger):
        self._open(host_id, peer_lists)
        self.timer = timer
        # link_log type {sw: [max_version, {'link': [version, state]}]}
        self.link_log = streams.link_log
        self.logger = logger

    def _open(self, host_id, peer_lists):
        self.sock = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.sock.setblocking(0)            # non-blocking
        self.sock.bind(peer_lists[host_id])
        del peer_lists[host_id]
        self.peer_lists = peer_lists

    def _digest(self):
        digest = {}
        for sw in self.link_log:
            digest[sw] = self.link_log[sw][0]
        return digest

    def _handle_msg(self, data, addr):
        '''
        |--- syn-->|
        |          |
        |<-- ack---|
        |          |
        |---ack2-->|
        '''
        if data['type'] == 'syn':
            self._handle_syn(data, addr)
        elif data['type'] == 'ack':
            self._handle_ack(data, addr)
        elif data['type'] == 'ack2':
            self._handle_ack2(data, addr)

    def _handle_syn(self, data, addr):
        self.logger.debug(
                "receive syn from %s, digest: %s" % (
                    addr[0], json.dumps(data['digest'])))
        ack_msg = {}
        for sw in data['digest']:
            if sw not in self.link_log:
                ack_msg[sw] = ['request', -1]
            else:
                if data['digest'][sw] > self.link_log[sw][0]:
                    ack_msg[sw] = ['request', self.link_log[sw][0]]
                elif data['digest'][sw] < self.link_log[sw][0]:
                    ack_msg[sw] = ['response', self.link_log[sw][0], {}]
                    for link in self.link_log[sw][1]:
                        if self.link_log[sw][1][link][0] > data['digest'][sw]:
                            ack_msg[sw][2][link] = [
                                    self.link_log[sw][1][link][0],
                                    self.link_log[sw][1][link][1]]
        for sw in self.link_log:
            if sw not in data['digest']:
                ack_msg[sw] = [
                        'response', self.link_log[sw][0], self.link_log[sw][1]]

        if ack_msg:
            self.logger.debug(
                    "send ack to %s, delta: %s" % (
                        addr[0], json.dumps(ack_msg)))
            self.sock.sendto(json.dumps(
                {'type': 'ack', 'delta': ack_msg}), addr)

    def _handle_ack(self, data, addr):
        self.logger.debug(
                "receive ack from %s, delta: %s" % (
                    addr[0], json.dumps(data['delta'])))
        ack2_msg = {}
        for sw in data['delta']:
            if sw not in self.link_log:
                if data['delta'][sw][0] == 'response':
                    self.link_log[sw] = [data['delta'][sw][1], data['delta'][sw][2]]
                else:
                    self.logger.warn('ack except response for unknown sw %s' % sw)

            elif data['delta'][sw][0] == 'response':
                for link in data['delta'][sw][2]:
                    if link not in self.link_log[sw][1] or\
                            self.link_log[sw][1][link][0] <\
                            data['delta'][sw][2][link][0]:
                        self.link_log[sw][1][link] = data['delta'][sw][2][link]
                if self.link_log[sw][0] < data['delta'][sw][1]:
                    self.link_log[sw][0] = data['delta'][sw][1]

            elif data['delta'][sw][0] == 'request':
                ack2_msg[sw] = ['response', self.link_log[sw][0], {}]
                for link in self.link_log[sw][1]:
                    if self.link_log[sw][1][link][0] > data['delta'][sw][1]:
                        ack2_msg[sw][2][link] = [
                                self.link_log[sw][1][link][0],
                                self.link_log[sw][1][link][1]]

        if ack2_msg:
            self.logger.debug(
                    "send ack2 to %s, delta: %s" % (
                        addr[0], json.dumps(ack2_msg)))
            self.sock.sendto(json.dumps(
                {'type': 'ack2', 'delta': ack2_msg}), addr)

    def _handle_ack2(self, data, addr):
        self.logger.debug(
                "receive ack2 from %s, delta: %s" % (
                    addr[0], json.dumps(data['delta'])))
        for sw in data['delta']:
            if sw in self.link_log and data['delta'][sw][0] == 'response':
                for link in data['delta'][sw][2]:
                    if link not in self.link_log[sw][1] or\
                            self.link_log[sw][1][link][0] <\
                            data['delta'][sw][2][link][0]:
                        self.link_log[sw][1][link] = data['delta'][sw][2][link]

                if self.link_log[sw][0] < data['delta'][sw][1]:
                    self.link_log[sw][0] = data['delta'][sw][1]

    def wait(self, selector):
        selector.wait([self.sock], [])

    def run(self, lists):
        # socket is readable
        if self.sock in lists[0]:
            self.logger.info("current link log: %s" % json.dumps(self.link_log))
            data, addr = self.sock.recvfrom(RECV_BUF_SIZE)
            self._handle_msg(byteify(json.loads(data)), addr)

        # check timer, time up per second
        if self.timer.time_up:
            addr = random.choice(self.peer_lists)
            self.logger.debug(
                    "send syn to %s, digest: %s" % (
                        addr[0], json.dumps(self._digest())))
            self.sock.sendto(json.dumps({
                'type': 'syn', 'digest': self._digest()
                }), addr)
