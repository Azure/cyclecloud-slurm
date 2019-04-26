import unittest
from slurmcc import parse_network, parse_nodelist


class SlurmCCTest(unittest.TestCase):

    def test_parse_network(self):
        self.assertEquals({"instances": "2"}, parse_network("Instances=2"))
        self.assertEquals({"instances": "2", "sn_single": True}, parse_network("Instances=2,SN_Single"))
        self.assertEquals({"instances": "2", "sn_single": True, "exclusive": True}, parse_network("Instances=2,SN_Single,Exclusive"))
        self.assertEquals({"instances": "2", "sn_single": True, "exclusive": True}, parse_network("Exclusive,Instances=2,SN_Single"))

    def test_parse_nodelist(self):
        self.assertEquals(["execute-1"], parse_nodelist("execute-1"))
        self.assertEquals(["execute-1", "execute-2"], parse_nodelist("execute-1,execute-2"))
        self.assertEquals(["execute-1", "execute-2", "execute-3", "execute-4"], parse_nodelist("execute-1,execute-2,execute-[3-4]"))
        self.assertEquals(["execute-1", "execute-2", "execute-13", "execute-23", "execute-14", "execute-24"], parse_nodelist("execute-1,execute-2,execute-[1-2][3-4]"))
                          

if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.test_parse_network']
    unittest.main()