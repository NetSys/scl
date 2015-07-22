## scl implementation

           +---------+          +---------+
           |   pox   |          |   pox   |
           +---------+          +---------+
             |  |  |     tcp      |  |  |
             1  2  3   openflow   1  2  3
             |  |  |              |  |  |
           +---------+          +---------+
           | ctrlscl |          | ctrlscl |
           +---------+          +---------+

                    udp broadcast

    +---------+       +---------+         +---------+
    | ovs_scl |       | ovs_scl |         | ovs_scl |
    +---------+       +---------+         +---------+
        |1   tcp openflow  |2                 |3
    +---------+       +---------+         +---------+
    |   ovs   |       |   ovs   |         |   ovs   |
    +---------+       +---------+         +---------+

## run scl routine

edit scl address and controller address in const.py

run sw_sc.py and ctrl_scl.py

``` Bash
./sw_scl.py     # on switch side
./ctrl_scl.py   # on controller side
```

run a controller function, pox as an example

``` Bash
./pox.py log.level --DEBUG forwarding.l2_learning
```

set up a network, mininet as an example
``` Bash
mn --switch ovsk --mac --controller remote,ip=127.0.0.1,port=6633
```

ctrl_scl will show the link state.