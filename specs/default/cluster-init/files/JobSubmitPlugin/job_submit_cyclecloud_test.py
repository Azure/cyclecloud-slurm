# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
#

import ctypes
import os
import unittest

class job_descriptor(ctypes.Structure):
    _fields_ = [('account', ctypes.c_char_p),
                ('acctg_freq', ctypes.c_char_p),
                ('admin_comment', ctypes.c_char_p),
                ('alloc_node', ctypes.c_char_p),
                ('alloc_resp_port', ctypes.c_int16),
                ('alloc_sid', ctypes.c_int32),
                ('argc', ctypes.c_int32),
                ('argv', ctypes.POINTER(ctypes.c_char_p)),
                ('array_inx', ctypes.c_char_p),
                ('array_bitmap', ctypes.POINTER(ctypes.c_long)),
                ('batch_features', ctypes.c_char_p),
                ('begin_time', ctypes.c_double),
                ('bitflags', ctypes.c_int32),
                ('burst_buffer', ctypes.c_char_p),
                ('ckpt_interval', ctypes.c_int16),
                ('ckpt_dir', ctypes.c_char_p),
                ('clusters', ctypes.c_char_p),
                ('cluster_features', ctypes.c_char_p),
                ('comment', ctypes.c_char_p),
                ('contiguous', ctypes.c_int16),
                ('core_spec', ctypes.c_int16),
                ('cpu_bind', ctypes.c_char_p),
                ('cpu_bind_type', ctypes.c_int16),
                ('cpu_freq_min', ctypes.c_int32),
                ('cpu_freq_max', ctypes.c_int32),
                ('cpu_freq_gov', ctypes.c_int32),
                ('cpus_per_tres', ctypes.c_char_p),
                ('deadline', ctypes.c_double),
                ('delay_boot', ctypes.c_int32),
                ('dependency', ctypes.c_char_p),
                ('end_time', ctypes.c_double),
                ('environment', ctypes.c_char_p),
                ('env_size', ctypes.c_int32),
                ('extra', ctypes.c_char_p),
                ('exc_nodes', ctypes.c_char_p),
                ('features', ctypes.c_char_p),
                ('fed_siblings_active', ctypes.c_int64),
                ('fed_siblings_viable', ctypes.c_int64),
                ('group_id', ctypes.c_int32),
                ('immediate', ctypes.c_int16),
                ('job_id', ctypes.c_int32),
                ('', ctypes.c_char_p),
                ('kill_on_node_fail', ctypes.c_int16),
                ('licenses', ctypes.c_char_p),
                ('mail_type', ctypes.c_int16),
                ('mail_user', ctypes.c_char_p),
                ('mcs_label', ctypes.c_char_p),
                ('mem_bind', ctypes.c_char_p),
                ('mem_bind_type', ctypes.c_int16),
                ('mem_per_tres', ctypes.c_char_p),
                ('name', ctypes.c_char_p),
                ('network', ctypes.c_char_p),
                ('nice', ctypes.c_int32),
                ('num_tasks', ctypes.c_int32),
                ('open_mode', ctypes.c_int8),
                ('origin_cluster', ctypes.c_char_p),
                ('other_port', ctypes.c_int16),
                ('overcommit', ctypes.c_int8),
                ('pack_job_offset', ctypes.c_int32),
                ('partition', ctypes.c_char_p),
                ('plane_size', ctypes.c_int16),
                ('power_flags', ctypes.c_int8),
                ('priority', ctypes.c_int32),
                ('profile', ctypes.c_int32),
                ('qos', ctypes.c_char_p),
                ('reboot', ctypes.c_int16),
                ('resp_host', ctypes.c_char_p),
                ('restart_cnt', ctypes.c_int16),
                ('req_nodes', ctypes.c_char_p),
                ('requeue', ctypes.c_int16),
                ('reservation', ctypes.c_char_p),
                ('script', ctypes.c_char_p),
                ('script_buf', ctypes.POINTER(ctypes.c_long)),
                ('shared', ctypes.c_int16),
                ('spank_job_env', ctypes.c_char_p),
                ('spank_job_env_size', ctypes.c_int32),
                ('task_dist', ctypes.c_int32),
                ('time_limit', ctypes.c_int32),
                ('time_min', ctypes.c_int32),
                ('tres_bind', ctypes.c_char_p),
                ('tres_freq', ctypes.c_char_p),
                ('tres_per_job', ctypes.c_char_p),
                ('tres_per_node', ctypes.c_char_p),
                ('tres_per_socket', ctypes.c_char_p),
                ('tres_per_task', ctypes.c_char_p),
                ('user_id', ctypes.c_int32),
                ('wait_all_nodes', ctypes.c_int16),
                ('warn_flags', ctypes.c_int16),
                ('warn_signal', ctypes.c_int16),
                ('warn_time', ctypes.c_int16),
                ('work_dir', ctypes.c_char_p),
                ('cpus_per_task', ctypes.c_int16),
                ('min_cpus', ctypes.c_int32),
                ('max_cpus', ctypes.c_int32),
                ('min_nodes', ctypes.c_int32),
                ('max_nodes', ctypes.c_int32),
                ('boards_per_node', ctypes.c_int16),
                ('sockets_per_board', ctypes.c_int16),
                ('sockets_per_node', ctypes.c_int16),
                ('cores_per_socket', ctypes.c_int16),
                ('threads_per_core', ctypes.c_int16),
                ('ntasks_per_node', ctypes.c_int16),
                ('ntasks_per_socket', ctypes.c_int16),
                ('ntasks_per_core', ctypes.c_int16),
                ('ntasks_per_board', ctypes.c_int16),
                ('pn_min_cpus', ctypes.c_int16),
                ('pn_min_memory', ctypes.c_int64),
                ('pn_min_tmp_disk', ctypes.c_int32),
                ('req_switch', ctypes.c_int32),
                ('select_jobinfo', ctypes.POINTER(ctypes.c_long)),
                ('std_err', ctypes.c_char_p),
                ('std_in', ctypes.c_char_p),
                ('std_out', ctypes.c_char_p),
                ('tres_req_cnt', ctypes.POINTER(ctypes.c_int64)),
                ('wait4switch', ctypes.c_int32),
                ('wckey', ctypes.c_char_p),
                ('x11', ctypes.c_int16),
                ('x11_magic_cookie', ctypes.c_char_p),
                ('x11_target_port', ctypes.c_int16)]
                

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
            job.network = ctypes.c_char_p(user_network)
            args = []
            
            if user_req_switches:
                args.append("--switches={}".format(user_req_switches))

            if user_network:
                args.append("--network={}".format(user_network))

            job.argc = len(args)
            job.argv = (ctypes.c_char_p * job.argc)(*args)

            job_ptr = ctypes.POINTER(job_descriptor)(job)
            lib.job_submit(job_ptr, 0, "")



            self.assertEquals(expected_switches, job_ptr.contents.req_switch)
        
        run_test(0, None, 1)
        run_test(5, None, 5)
        run_test(0, "Instances=5", 1)
        run_test(0, "Instances=5,sn_single", 0)
        

if __name__ == "__main__":
    unittest.main()