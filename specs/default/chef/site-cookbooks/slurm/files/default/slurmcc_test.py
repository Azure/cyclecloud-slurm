# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import unittest
from slurmcc import parse_network, NetworkSpecification


class SlurmCCTest(unittest.TestCase):

    def test_parse_network(self):
        self.assertEqual(NetworkSpecification(instances=2), parse_network("Instances=2"))
        self.assertEqual(NetworkSpecification(instances=2, sn_single=True), parse_network("Instances=2,SN_Single"))
        self.assertEqual(NetworkSpecification(instances=2, sn_single=True, exclusive=True), parse_network("Instances=2,SN_Single,Exclusive"))
        self.assertEqual(NetworkSpecification(instances=2, sn_single=True, exclusive=True), parse_network("Exclusive,Instances=2,SN_Single"))


if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.test_parse_network']
    unittest.main()
