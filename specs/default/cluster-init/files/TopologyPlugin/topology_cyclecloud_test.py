import ctypes
import unittest

lib = ctypes.CDLL(".libs/topology_cyclecloud.so")


class Test(unittest.TestCase):

    def test_basic(self):
        with open("test.csv", "w") as fw:
            fw.write("execute,pg1,ip-0A000000\r\n")
            fw.write("execute,pg0,ip-0A000001\n")
            fw.write("execute,pg0,ip-0A010004")
        
        def _topo_get_node_addr(nodename, nodearray, placementgroup, hostname):
            paddr = (ctypes.c_char_p * 1)("\0" * 512)
            ppath = (ctypes.c_char_p * 1)("\0" * 512)
            ret = lib.topo_get_node_addr(nodename, paddr, ppath)
            self.assertEquals(ret, 0)
            self.assertEquals(paddr[0], '%s.%s.%s' % (nodearray, placementgroup, hostname))
            self.assertEquals(ppath[0], 'switch.switch.node')
        _topo_get_node_addr("ip-0A000001", "execute", "pg0", "ip-0A000001")
        _topo_get_node_addr("ip-0A000000", "execute", "pg1", "ip-0A000000")
        _topo_get_node_addr("ip-0A010004", "execute", "pg0", "ip-0A010004")
        

if __name__ == "__main__":
    unittest.main()