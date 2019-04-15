#!/usr/bin/env python
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
import logging_init
import logging
from cyclecloud import autoscale_util, machine, clustersapi
from cyclecloud.autoscaler import Autoscaler, NoMachineFoundError
from slurmcc import SLURMDriver
import topology
import os
import json
import time
import slurmcc


class SLURMAutostart:
    def __init__(self, cc_config, clusters_api, driver, clock=time.time):
        self.cc_config = cc_config
        self.clusters_api = clusters_api
        self.driver = driver
        self.idle_timeout = int(self.cc_config.get("slurm.idle_timeout", 300))
        self.clock = clock
        
    def query_jobs(self):
        jobs = self.driver.get_jobs()
        return sorted(jobs, key=lambda x: 1 if x.executing_hostname is None else 0)
    
    def update_active_nodes(self, nodes):
        node_activity_path = self.cc_config.get("slurm.node_activity_file", "/opt/cycle/jetpack/node_activity.json")
        node_activity = {}
        
        if os.path.exists(node_activity_path):
            try:
                logging.debug("Loading %s", node_activity_path)
                with open(node_activity_path) as fr:
                    node_activity = json.load(fr)
            except Exception as e:
                logging.exception("Ignoring node activity because %s is inaccessible - %s", node_activity_path, str(e))
        
        last_update = node_activity.get("__last_update__")
        current_hostnames = set([node["hostname"] for node in nodes])
        
        for hostname in (set(node_activity.keys()) - current_hostnames) - set(["__last_update__"]):
            logging.debug("Hostname %s no longer exists as a CycleCloud node. Removing from node activity file.", hostname)
            node_activity.pop(hostname)
        
        since_last_update = self.clock() - last_update if last_update is not None else 0 
        reset_activity = last_update is not None and since_last_update > self.idle_timeout
        if reset_activity:
            logging.warn("Node activity has not been updated in less than %.0f seconds (%.0f). All nodes will be set as active again.", self.idle_timeout, since_last_update)
        
        now = self.clock()
        for node in nodes:
            hostname = node["hostname"]
            active = slurmcc.HostStates.is_active(node["state"])
            if reset_activity or active or hostname not in node_activity:
                node_activity[hostname] = now
                
            node["last_active_time"] = node_activity[hostname]
        
        try:
            node_activity["__last_update__"] = self.clock()
            with open(node_activity_path, "w") as fw:
                json.dump(node_activity, fw)
        except Exception as e:
            logging.exception("Could not write node activity because %s is inaccessible - %s", node_activity_path, str(e))
            
    def fetch_nodearray_definitions(self):
        nodearray_definitions = machine.fetch_nodearray_definitions(self.clusters_api, "PlacementGroupId")
        
        # translate into slurm terms
        for nodedef in nodearray_definitions:
            nodedef["minmemory"] = nodedef["memory"]
            nodedef["numcpus"] = nodedef["vcpuCount"]
        
        return nodearray_definitions
    
    def get_autoscale_machines(self, nodearray_definitions, slurm_hosts, cyclecloud_nodes):
        autoscale_machines = []
        for node in cyclecloud_nodes.itervalues():
            instance_attrs = {"PlacementGroupId": node.get("PlacementGroupId"),
                              "NodeId": node["NodeId"],
                              # just make the nodes active in the future if they are booting / not controlled by us
                              "last_active_time": self.clock() + 3600,
                              "state": "_booting_"
                             }
            private_ip = node.get("PrivateIp")
            
            if not private_ip:
                autoscale_machines.append(machine.from_node_record(nodearray_definitions, node, **instance_attrs))
                continue
            
            if private_ip not in slurm_hosts:
                autoscale_machines.append(machine.from_node_record(nodearray_definitions, node, **instance_attrs))
                continue
            
            slurm_host = slurm_hosts.pop(private_ip)
            node.update(slurm_host)
            instance_attrs["last_active_time"] = slurm_host["last_active_time"]
            instance_attrs["state"] = slurm_host["state"]
            autoscale_machines.append(machine.from_node_record(nodearray_definitions, node, **instance_attrs))
        
        return autoscale_machines
    
    def perform_idle_maintenance(self, idle_machines, unaccounted_down_hosts):
        omega = self.clock() - self.idle_timeout
        to_drain = []
        to_terminate = []

        for idle in idle_machines:
            machine_state = idle.get_attr("state")
            if slurmcc.HostStates.is_active(machine_state):
                logging.warn("Incorrectly declared machine %s as idle. Ignoring.", idle.hostname)
                continue
            
            if machine_state == "_booting_":
                continue
            
            if machine_state == slurmcc.HostStates.drained:
                logging.info("Terminating idle draining host %s", idle.hostname)
                to_terminate.append(idle)
                continue
            
            if idle.get_attr("last_active_time") < omega:
                to_drain.append(idle)
                logging.debug("Draining %s in state %s", idle.hostname, machine_state)
            else:
                logging.debug("Idle machine %s will not be drained for %.1f more seconds of inactivity", idle.hostname, idle.get_attr("last_active_time") - omega)
        
        if to_drain:
            drain_hostnames = [x.hostname for x in to_drain]
            logging.warn("Draining %d idle machines: %s", len(drain_hostnames), ",".join(drain_hostnames))
            self.driver.drain(drain_hostnames)
            
        if to_terminate:
            terminate_hostnames = [x.hostname for x in to_terminate]
            logging.warn("Terminating %d idle machines: %s", len(terminate_hostnames), ",".join(terminate_hostnames))
            self.clusters_api.shutdown(node_ids=[x.get_attr("NodeId") for x in to_terminate])
            self.driver.future(terminate_hostnames)
            
        if unaccounted_down_hosts:
            future_hostnames = [x["hostname"] for x in unaccounted_down_hosts]
            logging.warn("Setting %d unaccounted for hosts to FUTURE: %s", len(future_hostnames), ",".join(future_hostnames))
            self.driver.future(future_hostnames)
            
    def autostart(self):
        nodearray_definitions = self.fetch_nodearray_definitions()
        
        cyclecloud_nodes = autoscale_util.nodes_by_instance_id(self.clusters_api, nodearray_definitions)
        
        slurm_hosts = self.driver.get_hosts()
        self.update_active_nodes(slurm_hosts.values())
        
        autoscale_machines = self.get_autoscale_machines(nodearray_definitions, slurm_hosts, cyclecloud_nodes)
        
        # find down machines that we don't know about - we will set these as FUTURE - this is to overcome issue where a shutdown succeeds but
        # a call to future fails. TODO this might conflict with users who want to use existing nodes?
        unaccounted_down_hosts = []
        for host in slurm_hosts.values():
            if host["state"] == slurmcc.HostStates.down or host["unresponsive"]:
                unaccounted_down_hosts.append(host)
        
        logging.info("Found %d existing nodes" % len(autoscale_machines))
        autoscaler = Autoscaler(nodearray_definitions,
                                existing_machines=autoscale_machines,
                                default_placeby_attrs={},
                                start_enabled=self.cc_config.get("cyclecloud.cluster.autostart.start_enabled", True))
        
        jobs = self.query_jobs()
        
        for job in jobs:
            logging.debug(repr(job))
        
        for job in jobs:
            if job.executing_hostname and job.state in ["RUNNING", "COMPLETING"]:
                try:
                    logging.info("Job %s is executing on %s.", job.name, job.executing_hostname)
                    autoscaler.get_machine(job.executing_hostname).add_job(job, force=True)
                except NoMachineFoundError as e:
                    logging.warn("Could not find host %s for job %s in state %s. It most likely has been terminated and the SLURM queue has not been updated yet.",
                                 job.executing_hostname, job.name, job.state)
                    pass
            else:
                logging.info("Placing job %s", job.name)
                autoscaler.add_job(job)
        
        new_machine_requests = autoscaler.get_new_machine_requests()
        autoscale_request = autoscale_util.create_autoscale_request(new_machine_requests)
        logging.info(json.dumps(autoscale_request, indent=2))
        
        autoscale_util.scale_up(self.clusters_api, autoscale_request)
        
        idle_machines = autoscaler.get_idle_machines()
        self.perform_idle_maintenance(idle_machines, unaccounted_down_hosts)
        
        for mr in new_machine_requests:
            logging.info(mr)
            
        return idle_machines, new_machine_requests, autoscaler.get_all_machines()


if __name__ == "__main__":
    import jetpack.config
    topology.update_topology(jetpack.config)
    driver = SLURMDriver(jetpack.config)
    clusters_api = clustersapi.ClustersAPI(jetpack.config.get("cyclecloud.cluster.name"), jetpack.config, logging)
    SLURMAutostart(jetpack.config, clusters_api, driver).autostart()