# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
default[:slurm][:version] = "18.08.7-1"
default[:slurm][:arch] = "el7.x86_64"
default[:slurm][:user][:name] = 'slurm'
default[:slurm][:user][:uid] = 11100
default[:slurm][:user][:gid] = 11100
default[:munge][:user][:name] = 'munge'
default[:munge][:user][:uid] = 11101
default[:munge][:user][:gid] = 11101
# Time between a suspend call and when that node can be used again - i.e. 10 minutes to shutdown 
default[:slurm][:suspend_timeout] = 600
# Boot timeout
default[:slurm][:resume_timeout] = 1800
