import os
try:
    import logging_init
except ImportError as e:
    pass

import logging
import sys
import json
import shutil

from cyclecloud import clustersapi, autoscale_util
import re
import subprocess


def generate(provider_config):
    cluster = clustersapi.ClustersAPI(provider_config.get("cyclecloud.cluster.name"),
                                      provider_config,
                                      logging.getLogger())
    status = cluster.status(nodes=True)
    
    nodearrays = {}
    for node in status["nodes"]:
        if not node.get("PrivateIp"):
            continue
        
        placement_group_id = node.get("PlacementGroupId")
        if not placement_group_id:
            continue
        
        if "Hostname" not in node:
            node["Hostname"] = autoscale_util.get_hostname(node.get("PrivateIp"))
        
        nodearray_machine_type = "%s%s" % (node["Template"], node["MachineType"])
        nodearray_machine_type = nodearray_machine_type.replace("_", "")
        
        if nodearray_machine_type not in nodearrays:
            nodearrays[nodearray_machine_type] = {}
        switches = nodearrays[nodearray_machine_type]
        
        if placement_group_id not in switches:
            switches[placement_group_id] = set()
        switches[placement_group_id].add(node["Hostname"])
    
    return nodearrays
        

def store(nodearrays, fw):
    
    for nodearray, switches in nodearrays.iteritems():
        fw.write("SwitchName=%s Switches=%s\n" % (nodearray, ",".join(switches.keys())))
        for switch, nodes in switches.iteritems():
            fw.write("SwitchName=%s Nodes=%s\n" % (switch, ",".join(nodes)))
            
            
def load(fr):
    pattern = re.compile("^SwitchName=([a-zA-Z0-9_-]+) (Nodes|Switches)=([a-zA-Z0-9_,-]+)$")
    nodearrays = {}
    
    for line in fr:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            logging.warn("Could not parse line '%s'", line)
            continue
        
        child_type = match.group(2)
        if child_type == "Switches":
            pgs = {}
            for pg in match.group(3).split(","):
                pgs[pg] = set()
            nodearrays[match.group(1)] = pgs
        else:
            pg = match.group(1)
            nodearray = None
            for n in nodearrays.itervalues():
                if pg in n:
                    nodearray = n
                    break
                else:
                    print pg, "not in", n.keys()
            if not nodearray:
                logging.error("Could not find SwitchName=%s as a child of any other switch, i.e. a placement group as part of any nodearray.", pg)
                continue
            
            for hostname in match.group(3).split(","):
                nodearray[pg].add(hostname)
                
    return nodearrays


def update_topology(provider_config):
    logging.info("Checking for topology updates")
    new_switches = generate(provider_config)
    
    topology_path = "/etc/slurm/topology.conf"
    old_switches = {}
    
    if os.path.exists(topology_path):
        with open(topology_path, "r") as fr:
            old_switches = load(fr)
        
    if new_switches != old_switches:
        logging.info("Topology updates found, generating new topology.conf.")
        nodearray_differences = set(new_switches.keys()) ^ set(old_switches.keys())
        if nodearray_differences:
            logging.info("Nodearrays have changed: %s", " ".join(nodearray_differences))
        
        for key in set(new_switches.keys() + old_switches.keys()):
            pg_differences = set([tuple(x) for x in new_switches.get(key, {}).values()]) ^ set([tuple(x) for x in old_switches.get(key, {}).values()])
            if pg_differences:
                logging.info("Placement groups / node names have changed: %s", pg_differences)
        
        logging.debug("New topology")
        logging.debug(json.dumps(new_switches, indent=2, default=lambda x: list(x)))
        
        with open(topology_path + ".tmp", "w") as fw:
            store(new_switches, fw)
            
        shutil.move(topology_path + ".tmp", topology_path)
        logging.info("Calling scontrol reconfigure with updated %s", topology_path) 
        subprocess.check_call(["scontrol", "reconfigure"])
    else:
        logging.info("Topology has not changed")

     
if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.DEBUG)
    import jetpack.config
    update_topology(jetpack.config)
