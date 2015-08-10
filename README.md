## scl test topology

        +-------------------+       +-------------------+
        |    +---------+    |       |    +---------+    |
        |    |  pox1   |    |       |    |  pox2   |    |
        |    +---------+    |       |    +---------+    |
        |       |   |       |       |       |   |       |
        |VM1   of  of       |       |VM2   of  of       |
        |       |   |       |       |       |   |       |
        |    +---------+    |       |    +---------+    |
        |    |sclproxy |    |       |    |sclproxy |    |
        |    +---------+    |       |    +---------+    |
        |         |         |       |         |         |
        +---------|---------+       +---------|---------+
                          udp broadcast
        +---------|---------------------------|---------+
        |         |                           |         |
        |    +---------+                 +---------+    |
        |    |sclagent |                 |sclagent |    |
        |    +---------+                 +---------+    |
        |        |of                         |of        |
        |    +---------+                 +---------+    |
        |    |   sw1   |s1-eth2---s2-eth2|   sw2   |    |
        |    +---------+                 +---------+    |
        |      s1-eth1                     s2-eth1      |
        |VM3      |          mininet          |         |
        |      +-----+                     +-----+      |
        |      | h1  |                     | h2  |      |
        |      +-----+                     +-----+      |
        +-----------------------------------------------+

## run scl routine

set up 3 VMs, VM1 VM2 with pox and scl_proxy, VM3 with mininet and scl_agent. Put lib/ and scl_proxy.py in VM1 and VM2. Put lib/ scl_agent.py and net.py in VM3.

edit scl address and controller address in const.py

``` Bash
scl_proxy_intf = '192.168.1.1'      # on VM1
scl_proxy_intf = '192.168.1.2'      # on VM2
scl_agent_serv_port = 6633         # on VM3 for scl_agent of sw1
scl_agent_serv_port = 6634         # on VM3 for scl_agent of sw2
```

run scl_agent.py and scl_proxy.py in VMs

``` Bash
./scl_agent.py   # on VM3
./scl_proxy.py   # on VM1 or VM2
```

run a controller function, pox as an example

``` Bash
./pox.py log.level --DEBUG forwarding.l2_learning   # on VM1 or VM2
```

set up a network, mininet as an example

``` Bash
sudo ./mininet/net.py   # on VM3, put net.py in mininet directory
```

scl_proxy will show the change of link state.

``` Bash
sudo ip link set s1-eth2 down   # on VM3
sudo ip link set s1-eth2 up     # on VM3
```
