# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import ctypes
import os
import re
import unittest


"""
typedef struct job_descriptor { /* For submit, allocate, and update requests */
        char *account;          /* charge to specified account */
    
        uint16_t x11_target_port; /* target tcp port, 6000 + the display number */
} job_desc_msg_t;
"""


def generate_job_descriptor_class(lines):
    """
    ...
    typedef struct job_descriptor { /* For submit, allocate, and update requests */
            char *account;          /* charge to specified account */
            ...
            uint16_t x11_target_port; /* target tcp port, 6000 + the display number */
    } job_desc_msg_t;
    ...
    """
    
    pat = re.compile("^([a-zA-Z0-9_]+)[ ]*([*]*)[ ]*([a-zA-Z0-9_]+);.+$")
    fields = []
    in_job_description = False

    for line in lines:
        line = line.strip()

        if line.startswith("typedef struct job_descriptor"):
            in_job_description = True
        elif line.startswith("} job_desc_msg_t;"):
            in_job_description = False
        
        if not in_job_description:
            continue

        matches = pat.findall(line)
        if matches:
            match = matches[0]
            ctype_name = "c_{}".format(match[0])
            pointer = list(match[1])
            varname = match[2]

            if ctype_name.startswith("c_uint"):
                ctype_name = ctype_name.rstrip("_t")
            if ctype_name == "c_time_t":
                ctype_name = "c_double"

            if hasattr(ctypes, ctype_name):
                
                ctype = getattr(ctypes, ctype_name)
            else:
                ctype = ctypes.c_long
            if pointer:
                if ctype_name == "c_char":
                    ctype = ctypes.c_char_p
                    pointer.pop(0)
                while pointer:
                    ctype = ctypes.POINTER(ctype)
                    pointer.pop(0)
            # print(varname, ctype)
            fields.append((varname, ctype))

    class job_descriptor(ctypes.Structure):
        _fields_ = fields
    return job_descriptor


SLURM_H_PATH = os.path.expanduser("~/job_submit/slurm-20.11.7/slurm/slurm.h")
if os.getenv("SLURM_H_PATH", ""):
    SLURM_H_PATH = os.environ["SLURM_H_PATH"]

with open(SLURM_H_PATH) as fr:
    job_descriptor = generate_job_descriptor_class(fr.readlines())

lib = None
if os.getenv("JOB_SUBMIT_CYCLECLOUD"):
    ctypes.CDLL("libslurm.so", mode=ctypes.RTLD_GLOBAL)
    lib = ctypes.CDLL(".libs/job_submit_cyclecloud.so", mode=ctypes.RTLD_GLOBAL)


class Test(unittest.TestCase):

    def test_basic(self):
        '''job_submit(struct job_descriptor *job_desc,
                      uint32_t submit_uid,
		              char **err_msg)
        '''

        def run_test(user_req_switches, user_network, expected_switches):
            # this is only to be used when developing the job_submit_cyclecloud plugin
            # and run under docker, we want this ignored by jetpack test.
            if not os.getenv("JOB_SUBMIT_CYCLECLOUD"):
                return

            job = job_descriptor()
            job.req_switch = user_req_switches
            job.network = ctypes.c_char_p(user_network if user_network is None else user_network.encode())
            args = []
            
            if user_req_switches:
                args.append("--switches={}".format(user_req_switches))

            if user_network:
                args.append("--network={}".format(user_network))

            job.argc = len(args)
            job.argv = (ctypes.c_char_p * job.argc)(*[a.encode() for a in args])

            job_ptr = ctypes.POINTER(job_descriptor)(job)
            lib.job_submit(job_ptr, 0, "")

            self.assertEquals(expected_switches, job_ptr.contents.req_switch)
        
        run_test(0, None, 1)
        run_test(5, None, 5)
        run_test(0, "Instances=5", 1)
        print("running last test")
        run_test(0, "Instances=5,sn_single", 0)
        

if __name__ == "__main__":
    unittest.main()