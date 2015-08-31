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
        self.count = 0
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
            self.count = (self.count + 1) % 3
            self.time_up = True
            os.write(self.send_fd, 'x')
            time.sleep(next_call - time.time())
