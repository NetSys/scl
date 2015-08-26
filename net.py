from net_utils.topo import FatTree
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import Controller, RemoteController
from mininet.log import setLogLevel

DIR = 'bash net_utils'
#LOG_LEVEL = 'info'
LOG_LEVEL = 'debug'

class SclNet(object):
    def __init__(self, topo='FatTree'):
        self.switches = []
        self.hosts = []
        # TODO: hard code now, use config file instead
        self.ctrls = [3, 7, 8, 15]
        self.graph = nx.Graph()
        setLogLevel(LOG_LEVEL)
        # set up topology skeleton
        if topo is 'FatTree':
            self.skeleton = FatTree(4, self.graph, self.switches, self.hosts)
        # autoStaticArp doesnt works well, because we will move the IP in
        # the host interface to the internal port of the switch
        self.net = Mininet(topo=self.skeleton, controller=None)
        # FIXME: deal with handshake problem
        self.start_scl_agent()
        self.start_scl_proxy()
        # FIXME: now, to start pox, first download pox and put it in this directory
        self.start_controller()
        # set up ovs in each switch namespace
        self.start_switch()
        self.start_connection()
        # flow entries added before set-controller would be flushed
        self.config_ctrl_vlan()

    def start_scl_agent(self):
        sw_id = 0
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmd('python scl_agent.py %d &' % sw_id)
            sw_id = sw_id + 1

    def start_scl_proxy(self):
        ctrl_id = 0
        ctrls_num = len(self.ctrls)
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            # add default route to send broadcast msg
            host.cmdPrint('route add default gw %s' % host.IP())
            host.cmdPrint('python scl_proxy.py %d %d %s &' % (ctrl_id, ctrls_num, host.IP()))
            ctrl_id = ctrl_id + 1

    def start_controller(self):
        ctrl_id = 0
        pox_format='"%(asctime)s - %(name)s - %(levelname)s - %(message)s"'
        pox_datefmt='"%Y%m%d %H:%M:%S"'
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            host.cmd('python pox/pox.py log.level --DEBUG log --file=log/ctrl_%d.log,w --format=%s --datefmt=%s forwarding.l2_learning &' % (ctrl_id, pox_format, pox_datefmt))
            ctrl_id = ctrl_id + 1

    def start_switch(self):
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_br.sh %s' % (DIR, sw_name))

    def config_ctrl_vlan(self):
        # set vlan to some sw ports which connect to controller hosts
        # TODO: set intfs of other hosts another vlan tag, or default vlan?
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            host_intf = host.intfList()[0]
            sw_intf = host_intf.link.intf1\
                    if host_intf.link.intf1 is not host_intf\
                    else host_intf.link.intf2
            sw_name = sw_intf.name.split('-')[0]
            sw = self.net.getNodeByName(sw_name)
            # sw.ports index starts from 0, ovs index starts from 1
            sw_port = sw.ports[sw_intf] + 1
            self.net.getNodeByName(sw_name).cmdPrint(
                    '%s/config_ctrl_vlan.sh %s %s %d' % (
                        DIR, sw_name, sw_intf.name, sw_port))

    def start_connection(self):
        sw = self.net.getNodeByName(self.switches[3])
        sw.cmdPrint('tcpdump -i lo -enn -w s003.pcap &')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_connection.sh %s' % (DIR, sw_name))

    def run(self):
        CLI(self.net)

    def clearSwitches(self):
        sw = self.net.getNodeByName(self.switches[0])
        sw.cmdPrint('%s/stop_scl.sh' % DIR)
        sw.cmdPrint('ps -ef | grep scl')
        sw.cmdPrint('ps -ef | grep pox')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/clear_all.sh %s' % (DIR, sw_name))

    def stop(self):
        self.clearSwitches()
        self.net.stop()
