# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import datetime
import logging
import numbers
from subprocess import check_call, check_output


SLURM_NULL = "(null)"


class FieldSpec:
    def __init__(self, name, width=20, convert=str, default_value=""):
        self.name = name
        self.width = width
        self.convert = convert
        self.default_value = default_value
        
    def __str__(self):
        return "{}:{}".format(self.name, self.width)
        

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
            format_args.append("{}:{}".format(spec.name, spec.width)) 
        
        # '--format=%i|%C|%T|%D|%J|%m|%N|%P|%f|%h|%n|%Y|%s|%E'
        args = ['/bin/squeue', '-h', '-t', 'RUNNING,PENDING,COMPLETING', '--noheader', '-O', ','.join(format_args)] + jobs_args
        logging.debug(" ".join(args))
        return check_output(args)
    
    def invoke_sinfo(self):
        format_args = []
        
        for spec in self._host_format:
            format_args.append("{}:{}".format(spec.name, spec.width))
            
        args = ["sinfo", "-N", "--noheader", "-O", ",".join(format_args)]
        logging.debug(" ".join(args))
        return check_output(args)
    
    def _parse_fixed_width(self, line, format_specs):
        '''fixed width parsing of squeue/sinfo output'''
        format_specs = list(format_specs)
        ret = {}
        line = line.rstrip("\n")
        
        i = 0
        for spec in format_specs:
            length = int(self.override_format_lengths.get(spec.name, spec.width))
            if len(line) < i + length:
                raise RuntimeError("Line is too short: could not parse squeue line with format {} . {} < {} + {}\n'{}'".format(spec, len(line), i, length, line))
            value = line[i: i + length].strip()
            
            try:
                value = value or spec.default_value
                ret[spec.name] = spec.convert(value)
            except Exception as e:
                raise ValueError("Could not parse field {} with value '{}': {}".format(spec.name, value, str(e)))
            
            i = i + length
        
        if i != len(line):
            raise RuntimeError("Line is too long ({}): could not parse squeue line with format {} - '{}'".formate(len(line) - i, format_specs, line))
        
        return ret
    
    def parse_squeue_line(self, line):
        return self._parse_fixed_width(line, self._job_format)
    
    def parse_sinfo_line(self, line):
        return self._parse_fixed_width(line, self._host_format)
    
    def get_jobs(self, jobs=None):
        result = self.invoke_squeue(jobs)
        
        ret = []
        for line in result.splitlines(False):
            raw_job = self.parse_squeue_line(line)
            ret.append(raw_job)
            
        return ret
    
    def get_hosts(self):
        stdout = self.invoke_sinfo()
        if not stdout:
            return {}
        
        ret = {}
        for line in stdout.splitlines():
            host = self.parse_sinfo_line(line)
            
            ret[host["nodehost"]] = {"hostname": host["nodehost"],
                               "state": host["statecompact"].replace("*", ""),
                               "unresponsive": "*" in host["statecompact"],
                               "ncpus": host["cpus"],
                               "mem": float(host["memory"]) / 1024.,
                               "managed": False,
                               "reason_timestamp": host["timestamp"]}
        return ret
    
    def drain(self, hostnames):
        check_call(["scontrol", "update", "NodeName={}".format(",".join(hostnames)), "State=DRAIN", "Reason=CycleCloud autoscale"])
        
    def future(self, hostnames):
        check_call(["scontrol", "update", "NodeName={}".format(",".join(hostnames)), "State=FUTURE", "Reason=CycleCloud autoscale"])
        
    def update_job(self, job_id, key, value):
        check_call(["scontrol", "Update", "JobId={}".format(job_id), "{}={}".format(key, value)])
        
    def get_placement_group_from_feature(self, node):
        output = check_output(["scontrol", "show", "node", node, "--future", "-o"])
        active_features = None
        for expr in output.split():
            if "=" in expr:
                key, value = expr.split("=")
                if key.lower() == "activefeatures":
                    active_features = value.split(",")
        
        if active_features:
            for feature in active_features:
                if feature.lower().startswith("cyclepg"):
                    return feature.lower()
    

def _memory_converter_from_mb(value):
    if value is None or not value.strip():
        return None
    return parse_gb_size("mem", value)


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
    """
    Parses --network=Instances=2,SN_SINGLE,US,MPI ...
    See https://slurm.schedmd.com/sbatch.html
    
    
    Parameters:
    expr: string, The --network=expression

    Returns: NetworkSpecification 
    """

    network_args = {}
    for tok in expr.split(","):
        if "=" in tok:
            key, value = tok.split("=", 2)
            network_args[key.lower()] = value
        else:
            network_args[tok.lower()] = True
    network_spec = NetworkSpecification()
    
    if network_args.get("instances"):
        try:
            network_spec.instances = int(network_args.get("instances"))
        except Exception:
            logging.exception("Could not parse the number of instances for network expr %s", expr)
            
        network_spec.sn_single = network_args.get("sn_single", False)
    
    return network_spec


def format_network(network):
    ret = []
    for key, value in network.iteritems():
        if value is True:
            ret.append(key)
        else:
            ret.append("{}={}".format(key, value))
    return ",".join(ret)


def parse_nodelist(subprocess_module, nodelist_expr):
    nodes = []
    
    inside_bracket = False
    
    sub_exprs = []
    buf = cStringIO.StringIO()
    
    for ch in nodelist_expr:
        if not inside_bracket and ch == ",":
            sub_exprs.append(buf.getvalue())
            buf = cStringIO.StringIO()
            continue
        
        if ch == "[":
            inside_bracket = True
        elif ch == "]":
            inside_bracket = False
        
        buf.write(ch)
    
    sub_exprs.append(buf.getvalue())
    
    for e in sub_exprs:

        def expand(expr):
            if "[" not in expr:
                nodes.append(expr)
                return
            try:
                leftb = expr.rindex("[") 
                rightb = expr.rindex("]") 
                range_expr = expr[leftb + 1: rightb]
                
                for start_stop_expr in range_expr.split(","):
                    if "-" in start_stop_expr:
                        start, stop = range_expr.split("-")
                    else:
                        start = stop = start_stop_expr
                
                    while int(start) <= int(stop):
                        node = expr[0: leftb] + start + expr[rightb + 1:]
                        expand(node)
                        formatexpr = "%0" + str(len(start)) + "d"
                        start = formatexpr % (int(start) + 1)
            except Exception:
                logging.error("Failed while parsing '%s' as part of '%s'", expr, nodelist_expr)
                raise
                
        expand(e)
    return nodes


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
    

class NetworkSpecification:
    
    def __init__(self):
        self.sn_single = False
        self.instances = 0
        self.sn_single = False
        
        
class InvalidSizeExpressionError(RuntimeError):
    pass
    
    
def parse_gb_size(attr, value):
    if isinstance(value, numbers.Number):
        return value
    try:
        
        value = value.lower()
        if value.endswith("pb"):
            value = float(value[:-2]) * 1024
        elif value.endswith("p"):
            value = float(value[:-1]) * 1024
        elif value.endswith("gb"):
            value = float(value[:-2])
        elif value.endswith("g"):
            value = float(value[:-1])
        elif value.endswith("mb"):
            value = float(value[:-2]) / 1024
        elif value.endswith("m"):
            value = float(value[:-1]) / 1024
        elif value.endswith("kb"):
            value = float(value[:-2]) / (1024 * 1024)
        elif value.endswith("k"):
            value = float(value[:-1]) / (1024 * 1024)
        elif value.endswith("b"):
            value = float(value[:-1]) / (1024 * 1024 * 1024)
        else:
            try:
                value = int(value)
            except:
                value = float(value)
        
        return value
    except ValueError:
        raise InvalidSizeExpressionError("Unsupported size for {} - {}".format(attr, value))
