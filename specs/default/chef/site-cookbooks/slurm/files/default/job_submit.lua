-- Copyright (c) Microsoft Corporation. All rights reserved.
-- Licensed under the MIT License.

function slurm_job_submit(job_desc, part_list, submit_uid)
    if job_desc.argv ~= nil then
        for i = 0, job_desc.argc, 1 do
            if job_desc.argv[i] == "--switches" then
                slurm.log_info("--switches was set, ignoring.");
                return slurm.SUCCESS;
            end
        end
    end
    if job_desc.network ~= nil and job_desc.network ~= '' then
        if job_desc.network == "sn_single" then
            slurm.log_info("sn_single was set, ignoring.");
            return slurm.SUCCESS
        end
    end
    slurm.log_info("Setting reqswitch to 1.");
    job_desc.req_switch = 1;

    slurm.log_info("returning.");

    return slurm.SUCCESS
end

function slurm_job_modify(job_desc, job_rec, part_list, modify_uid)
    return slurm.SUCCESS
end

slurm.log_info("initialized job_submit_cyclecloud")
return slurm.SUCCESS