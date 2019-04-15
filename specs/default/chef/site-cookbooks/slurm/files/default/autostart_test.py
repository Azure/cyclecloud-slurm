import logging_init
import unittest
from autostart import SLURMAutostart, SLURMDriver
from cyclecloud.nodearrays import NodearrayDefinitions
from cyclecloud import autoscale_util, machine
from cyclecloud.autoscale_util import Record
from cyclecloud.machine import generate_placeby_values
from slurmcc import HostStates
import tempfile
import os
import uuid
from collections import OrderedDict


class MockClustersApi:
    
    def __init__(self, nodearray_defitions):
        self._nodes = []
        self._nodearray_defitions = nodearray_defitions
    
    def status(self, nodes=False):
        ret = {}
        nodearrays = {}
        for nodedef in self._nodearray_defitions:
            if nodedef["nodearray"] not in nodearrays:
                nodearrays[nodedef["nodearray"]] = {"buckets": [], "name": nodedef["nodearray"], "nodearray": {"PlacementGroupId": nodedef.get("PlacementGroupId")}}
            
            nodearray = nodearrays[nodedef["nodearray"]]
            nodearray["buckets"].append({"definition": {"machineType": nodedef["name"]},
                                         "maxPlacementGroupSize": 4,
                                         "virtualMachine": {"vcpuCount": nodedef["ncpus"], "memory": nodedef["mem"]}})
        
        ret["nodearrays"] = nodearrays.values()
        if nodes:
            ret["nodes"] = self._nodes
        return ret
    
    def nodes(self):
        return self._nodes
    
    def add_nodes(self, autoscale_request):
        for request in autoscale_request["sets"]:
            for _ in range(request["count"]):
                mt = self._nodearray_defitions.get_machinetype(request["nodearray"], request["definition"]["machineType"], request.get("placementGroupId"))
                name = request["nodearray"] + "-%d" % (len(self._nodes) + 1)
                node = Record({"name'": name, "template": request["nodearray"], "NodeId": autoscale_util.uuid("nodeid"), "MachineType": request["definition"]["machineType"]})
                node["PrivateIp"] = "10.0.0.%d" % len(self._nodes)
                node.update(mt)
                self._nodes.append(node)
                
    def shutdown(self, node_ids):
        self._nodes = [x for x in self._nodes if x["NodeId"] not in node_ids]
            

valid_fields = ["account", "allocnodes", "allocsid", "arrayjobid", "arraytaskid", "associd", "batchflag", "batchhost", "boardspernode", "burstbuffer", "burstbufferstate",
                "chptdir", "chptinter", "cluster", "clusterfeature", "command", "comment", "contiguous", "corespec", "cpufreq", "cpuspertask", "deadline", "dependency",
                "delayboot", "derivedec", "eligibletime", "endtime", "feature", "groupid", "groupname", "jobarrayid", "lastschedeval", "licenses", "maxcpus", "maxnodes",
                "mcslabel", "minmemory", "mintime", "mintmpdisk", "mincpus", "network", "nodelist", "ntperboard", "ntpercore", "ntpernode", "ntpersocket", "numcpus",
                "numnodes", "numtask", "origin", "originraw", "oversubscribe", "packjobid", "packjoboffset", "packjobidset", "partition", "priority", "prioritylong",
                "profile", "preemptime", "reason", "reasonlist", "reboot", "reqnodes", "reqswitch", "requeue", "reservation", "resizetime", "restartcnt", "resvport",
                "schednodes", "selectjobinfo", "siblingsactive", "siblingsactiveraw", "siblingsviable", "siblingsviableraw", "sockets", "sperboard", "starttime",
                "statecompact", "stderr", "stdout", "stepid", "stepname", "stepstate", "submittime", "threads", "timeleft", "timelimit", "timeused", "userid", "username",
                "workdir"]


class MockSLURMDriver(SLURMDriver):
    def __init__(self):
        SLURMDriver.__init__(self, {})
        self.job_id = 1
        self.queue = []
        self.hosts = []
        
    def invoke_squeue(self, jobs=None):
        assert jobs is None
        return self._generate_fixed_width(self.queue, self._job_format)
    
    def invoke_sinfo(self):
        return self._generate_fixed_width(self.hosts, self._host_format)
    
    def _generate_fixed_width(self, items, format_spec):
        lines = []
        for item in items:
            line = []
            for spec in format_spec:
                value = str(item.get(spec.name, spec.default_value))
                line.append(value + (" " * max(0, spec.width - len(value))))
            lines.append("".join(line))
        return "\n".join(lines)
        
    def sbatch(self, **kwargs):
        for key in kwargs:
            assert key in valid_fields, "unknown job argument %s" % key
            kwargs[key] = str(kwargs[key])
            
        if "jobid" not in kwargs:
            kwargs["jobid"] = str(self.job_id)
            self.job_id += 1
        kwargs["jobid"] = str(kwargs["jobid"])
        kwargs["numcpus"] = kwargs.get("numcpus", "1")
        kwargs["state"] = kwargs.get("state", "QUEUED")
        self.queue.append(kwargs)
        
    def qdel(self, jobid):
        self.queue = [x for x in self.queue if x["jobid"] != jobid]
        
    def add_host(self, **kwargs):
        self.hosts.append(kwargs)
        
    def drain(self, hostnames):
        matched = set()
        for host in self.hosts:
            if host["nodehost"] in hostnames:
                host["statecompact"] = "draining"
                matched.add(host["nodehost"])
                
        unmatched = matched - set(hostnames)
        if unmatched:
            raise RuntimeError("Unknown hostnames - %s" % unmatched)
                
    def future(self, hostnames):
        for host in self.hosts:
            if host["nodehost"] in hostnames:
                host["statecompact"] = "future"
        
        
class MockClock:
    
    def __init__(self, now=0):
        self.now = now
        
    def __call__(self):
        return self.now
    
    
class AutostartSetup:
    
    def __init__(self):
        self.nodedefs = NodearrayDefinitions()
        self.nodedefs.add_machinetype({"name": "a4", "nodearray": "execute", "ncpus": 4, "memory": 4 * 1024, "available": 100})
        for n, pg in enumerate(generate_placeby_values({"name": "execute", "Configuration": {"autoscale": {"max_placement_groups": 4}}}, "a4")):
            self.nodedefs.add_machinetype_with_placement_group(pg, {"name": "a4", "nodearray": "execute", "ncpus": 4, "memory": 4 * 1024, "available": 100,
                                                               "PlacementGroupId": pg, "placeby": "PlacementGroupId", "priority": 100 - n})
        self.clusters = MockClustersApi(self.nodedefs)
        self.driver = MockSLURMDriver()
        self.clock = MockClock(now=10000)
        self.node_activity_file = tempfile.mktemp()
        self.autostart = SLURMAutostart({"slurm.node_activity_file": self.node_activity_file}, self.clusters, self.driver, clock=self.clock)


class AutostartTest(unittest.TestCase):
    
    def setUp(self):
        unittest.TestCase.setUp(self)
        autoscale_util.set_uuid_func(autoscale_util.IncrementingUUID())
        self.test_setup = AutostartSetup()
        
    def tearDown(self):
        unittest.TestCase.tearDown(self)
        if os.path.exists(self.test_setup.node_activity_file):
            os.remove(self.test_setup.node_activity_file)
            
    def test_basic(self):
        nodedefs = NodearrayDefinitions()
        nodedefs.add_machinetype({"name": "a4", "nodearray": "execute", "ncpus": 4, "memory": 4 * 1024, "available": 100})
        for n, pg in enumerate(generate_placeby_values({"name": "execute", "Configuration": {"autoscale": {"max_placement_groups": 4}}}, "a4")):
            nodedefs.add_machinetype_with_placement_group(pg, {"name": "a4", "nodearray": "execute", "ncpus": 4, "memory": 4 * 1024, "available": 100,
                                                               "PlacementGroupId": pg, "placeby": "PlacementGroupId", "priority": 100 - n})
        
        clusters = MockClustersApi(nodedefs)
        driver = MockSLURMDriver()
        clock = MockClock()
        driver.sbatch(network="Instances=2,SN_Single,Exclusive", numcpus=4, minmemory="1gb")
        
        # 1 job, 2 exclusive nodes
        def run_autostart():
            a = SLURMAutostart({"slurm.node_activity_file": self.test_setup.node_activity_file}, clusters, driver, clock=clock)
            return a.autostart()
        
        idle, new, total = run_autostart()
        self.assertEquals(2, len(total))
        self.assertEquals(0, len(idle))
        self.assertEquals(1, len(new))
        self.assertEquals(2, new[0].instancecount)
        self.assertEquals(2, len(total))
        self.assertEquals('PlacementGroupId', new[0].placeby_attr)
        self.assertEquals('executea4pg0', new[0].placeby_value)
        
        # 1 job, 2 exclusive nodes + 1 job 2 non-exclusive nodes
        driver.sbatch(network="Instances=2,SN_Single", numcpus=4, minmemory="1gb")
        idle, new, total = run_autostart()
        self.assertEquals(4, len(total))
        self.assertEquals(0, len(idle))
        self.assertEquals(1, len(new))
        self.assertEquals(2, new[0].instancecount)
        self.assertEquals('PlacementGroupId', new[0].placeby_attr)
        self.assertEquals('executea4pg0', new[0].placeby_value)
        
        # 1 job, 2 exclusive nodes + 2 jobs w/ 2 non-exclusive nodes (notice it doesn't allocate a second)
        driver.sbatch(network="Instances=2,SN_Single", numcpus=4, minmemory="1gb")
        idle, new, total = run_autostart()
        
        self.assertEquals(4, len(total))
        self.assertEquals(0, len(idle))
        self.assertEquals(0, len(new))
        self.assertEquals(4, len(total))
        
#         # now add a non-grouped 2 node job
#         driver.sbatch(network="Instances=2,SN_Single,Exclusive", numcpus=4, minmemory="1gb")
#         print "BEFORE"
#         idle, new, total = run_autostart()
#         print "AFTER"
#         idle, new, total = run_autostart()
#         self.assertEquals(6, len(total))
#         self.assertEquals(0, len(idle))
#         self.assertEquals(1, len(new))
#         self.assertEquals(2, new[0].instancecount)
#         self.assertEquals('PlacementGroupId', new[0].placeby_attr)
#         self.assertEquals('executea4pg1', new[0].placeby_value)
        
        # now add a non-grouped 2 task job
        
        # removing the exclusive job, but since there are already 4 nodes started, we will rescatter the remaining 4 across them.
        driver.qdel("1")
        idle, new, total = run_autostart()
        self.assertEquals(4, len(total))
        self.assertEquals(0, len(idle))
        
        # remove one of the non-exclusive jobs, so now 2/4 nodes should be idle.
        driver.qdel("2")
        idle, new, total = run_autostart()
        self.assertEquals(2, len(idle))
        self.assertEquals(4, len(total))
        
        # submit another non-exclusive 2 node job to show that 0 nodes are idle again
        driver.sbatch(network="Instances=2,SN_Single", numcpus=4, minmemory="1gb")
        idle, new, total = run_autostart()
        self.assertEquals(0, len(idle))
        self.assertEquals(4, len(total))
        
        # empty the queue, total nodes are idle
        driver.qdel("3")
        driver.qdel("4")
        idle, new, total = run_autostart()
        self.assertEquals(4, len(idle))
        self.assertEquals(4, len(total))
        
        driver.add_host(nodehost="10.0.0.0", statecompact=HostStates.down, cpus="2", memory=8 * 1024)
        
        idle, new, total = run_autostart()
        
        clock.now += 150
        idle, new, total = run_autostart()
        clock.now += 151
        idle, new, total = run_autostart()
        self.assertEquals(driver.hosts[0]["statecompact"], HostStates.draining)
        driver.hosts[0]["statecompact"] = HostStates.drained
        
        idle, new, total = run_autostart()
        self.assertEquals(driver.hosts[0]["statecompact"], HostStates.future)
        
    def test_idle_maintenance(self):
        def reset():
            self.test_setup.driver.hosts = []
            self.test_setup.clusters._nodes = []
            
        autostart = self.test_setup.autostart
        
        def m(**host_orig):
            host_orig["cpus"] = str(host_orig.pop("cpus", "4"))
            host_orig["memory"] = str(host_orig.pop("memory", 8 * 1024))
            self.test_setup.driver.add_host(**host_orig)
            host = self.test_setup.driver.get_hosts().values()[0]
            host["last_active_time"] = host_orig["last_active_time"]
            
            assert "*" not in host["state"]
            host["NodeId"] = host.pop("NodeId", str(uuid.uuid4()))
            host["Template"] = host.pop("Template", "execute")
            host["MachineType"] = host.pop("MachineType", "a4")
            self.test_setup.clusters._nodes.append(host)
            return machine.from_node_record(self.test_setup.nodedefs, Record(host), **host)
        
        def h(**host):
            host["cpus"] = str(host.pop("cpus", 4))
            host["memory"] = str(host.pop("memory", 8 * 1024))
            host["hostname"] = host["nodehost"]
            self.test_setup.driver.add_host(**host)
            return host
        
        def _state():
            self.assertEquals(1, len(self.test_setup.driver.hosts))
            return self.test_setup.driver.get_hosts().values()[0]["state"]
        
        autostart.perform_idle_maintenance([m(nodehost="a100", statecompact=HostStates.allocated + "*", last_active_time=0)], [])
        self.assertEquals(_state(), HostStates.allocated)
        reset()
        
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.down, last_active_time=0)], [])
        self.assertEquals(_state(), HostStates.draining)
        reset()
        
        # leave draining nodes alone
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.draining + "*", last_active_time=0)], [])
        self.assertEquals(_state(), HostStates.draining)
        self.assertEquals(len(self.test_setup.clusters.nodes()), 1)
        reset()
        
        # terminate drained nodes
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.drained, last_active_time=0)], [])
        self.assertEquals(len(self.test_setup.clusters.nodes()), 0)
        self.assertEquals(_state(), HostStates.future)
        reset()
        
        # leave idle node up because it hasn't met 300 second threshold
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.idle, last_active_time=self.test_setup.clock() - 299)], [])
        self.assertEquals(len(self.test_setup.clusters.nodes()), 1)
        self.assertEquals(_state(), HostStates.idle)
        reset()
        
        # drain idle node because it hasn't met 300 second threshold
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.idle, last_active_time=self.test_setup.clock() - 301)], [])
        self.assertEquals(len(self.test_setup.clusters.nodes()), 1)
        self.assertEquals(_state(), HostStates.draining)
        reset()
        
        # drain idle node because it hasn't met 300 second threshold
        autostart.perform_idle_maintenance([m(nodehost="a101", statecompact=HostStates.down, last_active_time=self.test_setup.clock() - 301)], [])
        self.assertEquals(len(self.test_setup.clusters.nodes()), 1)
        self.assertEquals(_state(), HostStates.draining)
        reset()
        
        # drain idle node because it hasn't met 300 second threshold
        autostart.perform_idle_maintenance([], [h(statecompact=HostStates.down, nodehost="a200", last_active_time=self.test_setup.clock())])
        self.assertEquals(_state(), HostStates.future)
        reset()
        
    def test_update_node_activity(self):
        test_setup = AutostartSetup()
        
        def _node(**node):
            node["NodeId"] = node.pop("NodeId", str(uuid.uuid4()))
            node["Template"] = node.pop("Template", "execute")
            node["MachineType"] = node.pop("MachineType", "a4")
            return node
        
        # 
        a = _node(hostname="a100", state=HostStates.allocated)
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock(), a["last_active_time"])

        # job isn't idle, last_active_time is updated
        test_setup.clock.now += 100
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock(), a["last_active_time"])
        
        # 100 seconds have elapsed
        test_setup.clock.now += 100
        a["state"] = HostStates.idle
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock() - 100, a["last_active_time"])
        
        # Since we haven't run an update in longer than the idle timeout, 300 seconds, reset active time
        test_setup.clock.now += 100000
        a["state"] = HostStates.idle
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock(), a["last_active_time"])
        
        # last_active_time remains unchanged, as 200 < idle time out
        test_setup.clock.now += 200
        a["state"] = HostStates.idle
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock() - 200, a["last_active_time"])
        
        # last_active_time remains unchanged, as 200 < idle time out
        test_setup.clock.now += 200
        a["state"] = HostStates.idle
        test_setup.autostart.update_active_nodes([a])
        self.assertEquals(test_setup.clock() - 400, a["last_active_time"])
        
    def test_bug(self):
        self.test_setup.driver.sbatch(network="Instances=2,SN_Single,Exclusive", numcpus=4, minmemory="1gb")
        self.test_setup.driver.sbatch(network="Instances=2,SN_Single,Exclusive", numcpus=4, minmemory="1gb")
        self.test_setup.driver.sbatch(network="Instances=2,Exclusive", numcpus=4, reqswitch=1, minmemory="1gb")
        idle, new, total = self.test_setup.autostart.autostart()
        self.assertEquals(6, len(total))
        self.assertEquals(2, len(new))
        
        idle, new, total = self.test_setup.autostart.autostart()
        self.assertEquals(6, len(total))
        self.assertEquals(0, len(new))
        
        
if __name__ == "__main__":
    # import sys;sys.argv = ['', 'Test.testName']
    unittest.main()
