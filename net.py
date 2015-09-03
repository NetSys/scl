import os
from net_utils.topo import topo2file, FatTree, FatTreeOutBand
from mininet.net import Mininet
from mininet.cli import CLI
from mininet.node import Controller, RemoteController
from mininet.log import setLogLevel

DIR = 'bash net_utils'
#LOG_LEVEL = 'info'
LOG_LEVEL = 'debug'

class SclNet(object):
    def __init__(self, topo='fattree'):
        self.switches = []
        self.hosts = []
        self.topo = topo
        # TODO: hard code now, use config file instead
        self.ctrls = [3, 7, 8, 15]
        setLogLevel(LOG_LEVEL)
        # set up topology skeleton
        if self.topo is 'fattree':
            self.skeleton = FatTree(4, self.switches, self.hosts)
        elif self.topo is 'fattreeoutband':
            self.skeleton = FatTreeOutBand(4, self.switches, self.hosts, self.ctrls)
        # autoStaticArp doesnt works well, because we will move the IP in
        # the host interface to the internal port of the switch
        self.net = Mininet(topo=self.skeleton, controller=None)
        # write topology to file
        self.file_name = os.path.abspath('./conf') + '/' + topo + '.json'
        topo2file(self.file_name, self.net, self.switches, self.hosts, self.ctrls)
        if topo is 'fattree':
            # set up ovs in each switch namespace
            # NOTE: first, we need to start_switch, which will change intfs
            self.start_switch()
            self.start_scl_agent()
            self.start_scl_proxy()
            # FIXME: now, to start pox, download pox and mv it in this directory
            self.start_controller()
            self.start_inband_connection()
            # flow entries added before set-controller would be flushed
            self.config_ctrl_vlan()
        if topo is 'fattreeoutband':
            self.set_static_arps()
            self.start_dp_switch()
            self.start_ctrl_switch()
            self.config_ctrl_host()
            self.start_scl_agent()
            self.start_scl_proxy(add_route=False)
            # FIXME: now, to start pox, download pox and mv it in this directory
            self.start_controller()
            self.start_outband_connection()

    def set_static_arps(self):
        ctrls = [self.hosts[ctrl] for ctrl in self.ctrls]
        hosts = [host for host in self.hosts if host not in ctrls]
        arps = []
        for host_name in hosts:
            host = self.net.getNodeByName(host_name)
            arps.append((host.IP(), host.MAC()))
        for host_name in hosts:
            host = self.net.getNodeByName(host_name)
            for arp in arps:
                if arp[0] == host.IP():
                    continue
                host.cmdPrint('arp -s %s %s' % (arp[0], arp[1]))

    def start_scl_agent(self):
        sw_id = 0
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmd('python scl_agent.py %d %s > log/scl_agent_%d.log 2>&1 &' % (sw_id, sw.IP(), sw_id))
            sw_id = sw_id + 1

    def start_scl_proxy(self, add_route=True):
        ctrl_id = 0
        ctrls_num = len(self.ctrls)
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            # add default route to send broadcast msg
            if add_route:
                host.cmdPrint('route add default gw %s' % host.IP())
            host.cmdPrint('python scl_proxy.py %d %d %s > log/scl_proxy_%d.log 2>&1 &' % (ctrl_id, ctrls_num, host.IP(), ctrl_id))
            ctrl_id = ctrl_id + 1

    def start_controller(self):
        ctrl_id = 0
        pox_format='"%(asctime)s - %(name)s - %(levelname)s - %(message)s"'
        pox_datefmt='"%Y%m%d %H:%M:%S"'
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            # NOTE: hard code
            #host.cmd('python pox/pox.py log.level --DEBUG log --file=log/ctrl_%d.log,w --format=%s --datefmt=%s scl_routing --name=%s &' % (ctrl_id, pox_format, pox_datefmt, self.file_name))
            host.cmd('python pox/pox.py log.level --DEBUG log --format=%s --datefmt=%s scl_routing --name=%s > log/ctrl_%d.log 2>&1 &' % (pox_format, pox_datefmt, self.file_name, ctrl_id))
            ctrl_id = ctrl_id + 1

    def start_switch(self):
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_br.sh %s' % (DIR, sw_name))

    def start_dp_switch(self):
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_dp_br.sh %s' % (DIR, sw_name))

    def start_ctrl_switch(self):
        for sw_name in self.switches:
            sw_name = 'c' + sw_name[1:]
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_ovs.sh %s' % (DIR, sw_name))
            sw.cmdPrint('%s/create_ctrl_br.sh %s' % (DIR, sw_name))

    def config_ctrl_host(self):
        for ctrl in self.ctrls:
            host = self.net.getNodeByName(self.hosts[ctrl])
            ip = host.IP()
            # config ip to control plane interface
            # add default route to send broadcast msg
            host.cmdPrint('ifconfig %s-eth0 0' % self.hosts[ctrl])
            host.cmdPrint('ifconfig %s-eth1 %s/8' % (self.hosts[ctrl], ip))
            host.cmdPrint('route add default gw %s'% ip)

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

    def start_inband_connection(self):
        sw = self.net.getNodeByName(self.switches[3])
        #sw.cmdPrint('tcpdump -i lo -enn -w s003.pcap &')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw.cmdPrint('%s/start_inband_connection.sh %s' % (DIR, sw_name))

    def start_outband_connection(self):
        sw = self.net.getNodeByName(self.switches[3])
        #sw.cmdPrint('tcpdump -i lo -enn -w s003.pcap &')
        for sw_name in self.switches:
            sw = self.net.getNodeByName(sw_name)
            sw_intf = sw.intfList()[-1]
            ctrl_intf = sw_intf.link.intf1\
                    if sw_intf.link.intf1 is not sw_intf\
                    else sw_intf.link.intf2
            ctrl_name = ctrl_intf.name.split('-')[0]
            assert ctrl_name[0] == 'c'
            outport = sw.ports[sw_intf] + 1
            sw.cmdPrint(
                    '%s/start_outband_connection.sh %s %d' % (
                        DIR, sw_name, outport))

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
        if self.topo is 'fattreeoutband':
            for sw_name in self.switches:
                sw_name = 'c' + sw_name[1:]
                sw = self.net.getNodeByName(sw_name)
                sw.cmdPrint('%s/clear_all.sh %s' % (DIR, sw_name))

    def stop(self):
        self.clearSwitches()
        self.net.stop()
