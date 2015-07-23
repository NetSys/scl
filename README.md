## scl test topology

        +-------------------+       +-------------------+
        |    +---------+    |       |    +---------+    |
        |    |  pox1   |    |       |    |  pox2   |    |
        |    +---------+    |       |    +---------+    |
        |      |  |  |      |       |      |  |  |      |
        |VM1  of of of      |       |VM2  of of of      |
        |      |  |  |      |       |      |  |  |      |
        |    +---------+    |       |    +---------+    |
        |    | ctrlscl |    |       |    | ctrlscl |    |
        |    +---------+    |       |    +---------+    |
        |         |         |       |         |         |
        +---------|---------+       +---------|---------+
                          udp broadcast
        +---------|---------------------------|---------+
        |         |                           |         |
        |    +---------+                 +---------+    |
        |    |  sw_scl |                 |  sw_scl |    |
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

set up 3 VMs, VM1 VM2 with pox and ctrl_scl, VM3 with mininet and sw_scl. Put lib/ and ctrl_scl.py in VM1 and VM2. Put lib/ sw_scl.py and net.py in VM3.

edit scl address and controller address in const.py

``` Bash
ctrl_scl_intf = '192.168.1.1'   # on VM1
ctrl_scl_intf = '192.168.1.2'   # on VM2
sw_scl_serv_port = 6633         # on VM3 for sw_scl of sw1
sw_scl_serv_port = 6634         # on VM3 for sw_scl of sw2
```

run sw_scl.py and ctrl_scl.py in VMs

``` Bash
./sw_scl.py     # on VM3
./ctrl_scl.py   # on VM1 or VM2
```

run a controller function, pox as an example

``` Bash
./pox.py log.level --DEBUG forwarding.l2_learning   # on VM1 or VM2
```

set up a network, mininet as an example

``` Bash
sudo ./mininet/net.py   # on VM3, put net.py in mininet directory
```

ctrl_scl will show the change of link state.

``` Bash
sudo ip link set s1-eth2 down   # on VM3
sudo ip link set s1-eth2 up     # on VM3
```
