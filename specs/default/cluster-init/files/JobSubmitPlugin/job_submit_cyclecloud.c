// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

#include "string.h"
#include "stdio.h"

#include "slurm/slurm.h"
#include "src/slurmctld/slurmctld.h"
#include "src/common/log.h"
#include "src/common/slurm_xlator.h"



// Required by slurm plugins. See https://slurm.schedmd.com/job_submit_plugins.html
const char plugin_name[] = "CycleCloud job submission plugin";
const char plugin_type[] = "job_submit/cyclecloud";
const uint32_t plugin_version   = SLURM_VERSION_NUMBER;


extern int init(void)
{
    return SLURM_SUCCESS;
}


extern void fini(void)
{
}


extern int job_submit(struct job_descriptor *job_desc,
                      uint32_t submit_uid,
		              char **err_msg)
{
    int i;

    info("req_switch=%d network='%s'", job_desc->req_switch, job_desc->network);

    // member variables aren't zeroed out by slurm, so we have to look at args
	// if (job_desc->req_switch > 0 && job_desc->req_switch != -2) {
    //     info("--switch was set, ignoring.");
    //     return SLURM_SUCCESS;
    // }

    for (i = 0; i < job_desc->argc; i++) {
        if (strstr(job_desc->argv[i], "--switches")) {
            info("--switches was set, ignoring.");
            return SLURM_SUCCESS;
        }
    }

    if (job_desc->network) {
        char *network_expr = strdup(job_desc->network);
        if (strstr(network_expr, "sn_single")) {
            info("sn_single was set, ignoring.");
            return SLURM_SUCCESS;
        }
    }

    info("Setting reqswitch to 1.");
    job_desc->req_switch = 1;

    info("returning.");
    return SLURM_SUCCESS;
}


extern int job_modify(struct job_descriptor *job_desc,
		              struct job_record *job_ptr,
                      uint32_t submit_uid)
{
	return SLURM_SUCCESS;
}
