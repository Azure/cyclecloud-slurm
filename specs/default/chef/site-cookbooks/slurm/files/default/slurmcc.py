# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import logging
import numbers
import os
import random

import requests


class FieldSpec:
    def __init__(self, name, width=20, convert=str, default_value=""):
        self.name = name
        self.width = width
        self.convert = convert
        self.default_value = default_value
        
    def __str__(self):
        return "{}:{}".format(self.name, self.width)
        

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
        network_spec.exclusive = network_args.get("exclusive", False)
    
    return network_spec


def format_network(network):
    ret = []
    for key, value in network.items():
        if value is True:
            ret.append(key)
        else:
            ret.append("{}={}".format(key, value))
    return ",".join(ret)


class NetworkSpecification:
    
    def __init__(self, sn_single=False, instances=0, exclusive=False):
        self.sn_single = sn_single
        self.instances = instances
        self.exclusive = exclusive
        
    def __eq__(self, other):
        return self.sn_single == other.sn_single and self.instances == other.instances \
            and self.exclusive == other.exclusive
            
    def __str__(self):
        return "Network(sn_single=%s, instances=%d, exclusive=%s)" % (self.sn_single, self.instances, self.exclusive)
    
    def __repr__(self):
        return str(self)
        
        
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


def custom_chaos_mode(action):
    def wrapped(func):
        return chaos_mode(func, action)
    return wrapped


def chaos_mode(func, action=None):
    def default_action():
        raise random.choice([RuntimeError, ValueError, requests.exceptions.ConnectionError])("Random failure")
    
    action = action or default_action
    
    def wrapped(*args, **kwargs):
        if is_chaos_mode():
            return action()
            
        return func(*args, **kwargs)
    
    return wrapped


def is_chaos_mode():
    return random.random() < float(os.getenv("CYCLECLOUD_SLURM_CHAOS_MODE", 0))
