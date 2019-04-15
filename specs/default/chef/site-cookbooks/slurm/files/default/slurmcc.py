from cyclecloud import autoscale_util
import subprocess
import logging
from cyclecloud.job import Job, PackingStrategy
import datetime
from subprocess import check_call


class FieldSpec:
    def __init__(self, name, width=20, convert=str, default_value=""):
        self.name = name
        self.width = width
        self.convert = convert
        self.default_value = default_value
        
    def __str__(self):
        return "%s:%s" % (self.name, self.width)
        

class SLURMDriver:

    def __init__(self, provider_config):
        # leave an ability to override these lengths, as it is hard to predict what the proper size should be.
        self.override_format_lengths = provider_config.get("slurm.field.width", {})
        self.eligibletime_threshold = int(provider_config.get("slurm.eligibletime.threshold", 10)) * 60
        self._job_format = [FieldSpec("jobid"), FieldSpec("state"), FieldSpec("reqswitch", 5, int, 0), FieldSpec("network", 60), FieldSpec("numnodes", 10, int, 0), FieldSpec("numtasks", 10, int, 0), 
                            FieldSpec("minmemory", 10, _memory_converter_from_mb), FieldSpec("partition", 40), FieldSpec("feature", 100), FieldSpec("oversubscribe", 10), FieldSpec("eligibletime", 20, _convert_timestamp),
                            FieldSpec("timeleft", 20, _convert_timeleft), FieldSpec("numcpus", 10, int), FieldSpec("dependency", 150), FieldSpec("nodelist", 1024)
                  ]
        self._host_format = [FieldSpec("nodehost", 100), FieldSpec("statecompact", 30), FieldSpec("cpus", 10, int), FieldSpec("memory", 10, _memory_converter_from_mb),
                   FieldSpec("reason", 50), FieldSpec("timestamp", 30, _convert_timestamp)]
        
        for spec in self._job_format + self._host_format:
            spec.width = int(self.override_format_lengths.get(spec.name, spec.width))
    
    def invoke_squeue(self, jobs=None):
        if jobs:
            jobs_args = ["--job", ",".join(jobs)]
        else:
            jobs_args = []
        format_args = []
        for spec in self._job_format:
            format_args.append("%s:%s" % (spec.name, spec.width)) 
        
        # '--format=%i|%C|%T|%D|%J|%m|%N|%P|%f|%h|%n|%Y|%s|%E'
        args = ['/bin/squeue', '-h', '-t', 'RUNNING,PENDING,COMPLETING', '--noheader', '-O', ','.join(format_args)] + jobs_args
        logging.debug(" ".join(args))
        return subprocess.check_output(args)
    
    def invoke_sinfo(self):
        format_args = []
        for spec in self._host_format:
            format_args.append("%s:%s" % (spec.name, spec.width))
        args = ["sinfo", "-N", "--noheader", "-O", ",".join(format_args)]
        logging.debug(" ".join(args))
        return subprocess.check_output(args)
    
    def _parse_fixed_width(self, line, format_specs):
        '''fixed width parsing of squeue/sinfo output'''
        format_specs = list(format_specs)
        ret = {}
        line = line.rstrip("\n")
        
        i = 0
        for spec in format_specs:
            length = int(self.override_format_lengths.get(spec.name, spec.width))
            if len(line) < i + length:
                raise RuntimeError("Line is too short: could not parse squeue line with format %s . %d < %d + %d\n'%s'" % (spec, len(line), i, length, line))
            value = line[i: i + length].strip()
            
            try:
                value = value or spec.default_value
                ret[spec.name] = spec.convert(value)
            except Exception as e:
                raise ValueError("Could not parse field %s with value '%s': %s" %( spec.name, value, str(e)))
            
            i = i + length
        
        if i != len(line):
            raise RuntimeError("Line is too long (%d): could not parse squeue line with format %s - '%s'" % (len(line) - i, format_specs, line))
        
        return ret
    
    def parse_squeue_line(self, line):
        return self._parse_fixed_width(line, self._job_format)
    
    def parse_sinfo_line(self, line):
        return self._parse_fixed_width(line, self._host_format)
    
    def get_jobs(self, jobs=None):
        result = self.invoke_squeue(jobs)
        
        autoscale_jobs = []
        eligible_threshold = datetime.datetime.now() + datetime.timedelta(0, self.eligibletime_threshold)
        
        one_hour = datetime.timedelta(0, 3600)
        epoch = datetime.datetime.strptime("0", "%S")
        
        for line in result.splitlines(False):
            '''
                %s Node selection plugin specific data for a job. Possible data includes: Geometry requirement of resource allocation (X,Y,Z dimensions),
                   Connection type (TORUS, MESH, or NAV == torus else mesh), Permit rotation of geometry (yes or no), Node use (VIRTUAL or COPROCESSOR), etc. (Valid for jobs only)
            '''
            raw_job = self.parse_squeue_line(line)
            
            if raw_job["eligibletime"] and raw_job["eligibletime"] > eligible_threshold:
                logging.debug("Ignoring job %s as it will not be running for at least %.1f minutes. (%s)",
                              raw_job["jobid"], self.eligibletime_threshold / 60., raw_job["eligibletime"])
                continue
            
            if raw_job["timeleft"]:
                weight = min(1, (raw_job["timeleft"] - epoch).total_seconds() / one_hour)
            else:
                weight = 1

            numnodes = int(raw_job["numnodes"]) if "numnodes" in raw_job else None
            
            network_attrs = parse_network(raw_job["network"])
            if "instances" in network_attrs:
                numnodes = int(network_attrs["instances"])
            
            ncpus = int(raw_job["numcpus"]) / max(numnodes, 1)
            
            if raw_job["dependency"]:
                # TODO ideally, if the endtime was within say 10 minutes we should start the dependencies?
                logging.debug("Skipping %s because it has dependencies", raw_job["jobid"])
                continue
            
            def nodes_to_list(x):
                return x.split(",") if x and x != "(null)" else []
            
            # TODO pending / hints
            assigned_nodes = nodes_to_list(raw_job["nodelist"]) if raw_job["state"] == "RUNNING" else []
            
            resources = {"ncpus": int(ncpus)}
            if raw_job["minmemory"]:
                resources["minmemory"] = autoscale_util.parse_gb_size("minmemory", raw_job["minmemory"])
                
            exclusive = raw_job.get("over_subscribe") == "NO" or network_attrs.get("exclusive", False)
            is_grouped = network_attrs.get("sn_single") or raw_job["reqswitch"] > 0
            placeby = "PlacementGroupId" if is_grouped else None
            packing_strategy = PackingStrategy.SCATTER if numnodes else PackingStrategy.PACK
            
#             numnodes_or_tasks = (numnodes or 1) * max(int(raw_job["numtask"]), 1) 
            
            assigned_nodes = assigned_nodes or [None]
            for assigned_node in assigned_nodes:
                autoscale_job = Job(name=raw_job["jobid"],
                                    nodes=numnodes,
                                    nodearray=None,
                                    exclusive=exclusive,
                                    packing_strategy=packing_strategy,
                                    resources=resources, 
                                    placeby=placeby,
                                    placeby_value=None, 
                                    executing_hostname=assigned_node,
                                    runtime=weight,
                                    state=raw_job["state"])
                autoscale_jobs.append(autoscale_job)
                
        return autoscale_jobs
    
    def get_hosts(self):
        stdout = self.invoke_sinfo()
        if not stdout:
            return {}
        
        ret = {}
        for line in stdout.splitlines():
            host = self.parse_sinfo_line(line)
            
            private_ip = autoscale_util.get_private_ip(host["nodehost"])
            ret[private_ip] = {"hostname": host["nodehost"],
                               "state": host["statecompact"].replace("*", ""),
                               "unresponsive": "*" in host["statecompact"],
                               "ncpus": host["cpus"],
                               "mem": float(host["memory"]) / 1024.,
                               "managed": False,
                               "reason_timestamp": host["timestamp"]}
        return ret
    
    def drain(self, hostnames):
        check_call(["scontrol", "update", "NodeName=%s" % ",".join(hostnames), "State=DRAIN", "Reason=CycleCloud autoscale"])
        
    def future(self, hostnames):
        check_call(["scontrol", "update", "NodeName=%s" % ",".join(hostnames), "State=FUTURE", "Reason=CycleCloud autoscale"])
        
    def update_job(self, job_id, key, value):
        subprocess.check_call(["scontrol", "Update", "JobId=%s" % job_id, "%s=%s" % (key, value)])
    

def _memory_converter_from_mb(value):
    if value is None or not value.strip():
        return None
    return autoscale_util.parse_gb_size("mem", value)


def _convert_timestamp(value):
    if "Unknown" == value or "N/A" == value:
        return None
    
    if value is None or not value.strip():
        return None
    try:
        return datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as e:
        logging.debug(str(e))
        return None


def _convert_timeleft(value):
    if value is None or not value or value in ["N/A", "UNLIMITED"]:
        return None
    
    for tformat in ["%M:%S", "%H:M:%S", "%S", "%d-%H:%M:%S"]:
        try:
            return datetime.datetime.strptime(value, tformat)
        except ValueError as e:
            pass
        
    logging.warn("Could not parse timeleft value %s", value)
    return None
        

def parse_network(expr):
    ret = {}
    for tok in expr.split(","):
        if "=" in tok:
            key, value = tok.split("=", 2)
            ret[key.lower()] = value
        else:
            ret[tok.lower()] = True
    return ret


def format_network(network):
    ret = []
    for key, value in network.iteritems():
        if value is True:
            ret.append(key)
        else:
            ret.append("%s=%s" % (key, value))
    return ",".join(ret)


class HostStates:
    allocated = "allocated"
    completing = "completing"
    down = "down"
    drained = "drained"
    draining = "draining"
    fail = "fail"
    failing = "failing"
    future = "future"
    idle = "idle"
    maint = "maint"
    mixed = "mixed"
    perfctrs = "perfctrs"
    power_down = "power_down"
    power_up = "power_up"
    reserved = "reserved"
    unknown = "unknown"
    
    @staticmethod
    def is_active(state):
        return state in [HostStates.allocated, HostStates.completing, HostStates.draining, HostStates.mixed]
