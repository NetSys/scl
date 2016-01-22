import os
import datetime
import threading
import time


class Timer(object):
    '''
    periodically wake up select, send msg (gossipe and link state request)
    '''
    def __init__(self, logger):
        r, w = os.pipe()
        self.listen_fd = r
        self.send_fd = w
        self.link_state_rqst_count = 0
        self.flow_table_rqst_count = 0
        self.flow_stats_rqst_count = 0
        self.try_te_count = 0
        self.time_up = False
        self.timer_thread = threading.Thread(target=self.timer)
        self.timer_thread.daemon = True
        self.logger = logger

    def start(self):
        self.timer_thread.start()

    def wait(self, selector):
        self.time_up = False
        selector.wait([self.listen_fd], [])

    def run(self, lists):
        if self.listen_fd in lists[0]:
            os.read(self.listen_fd, 1)

    def timer(self):
        time.sleep(5)   # for setup
        next_call = time.time()
        while True:
            self.logger.debug('timer: %s' % datetime.datetime.now())
            next_call = next_call + 1;
            self.link_state_rqst_count = (self.link_state_rqst_count + 1) % 3
            self.flow_table_rqst_count = (self.flow_table_rqst_count + 1) % 5
            self.flow_stats_rqst_count = (self.flow_stats_rqst_count + 1) % 2
            self.try_te_count = (self.try_te_count + 1) % 30
            self.time_up = True
            os.write(self.send_fd, 'x')
            time.sleep(next_call - time.time())
