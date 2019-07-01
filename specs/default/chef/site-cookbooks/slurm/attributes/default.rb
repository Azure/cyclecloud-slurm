# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
default[:slurm][:version] = "17.11.7-1"
default[:slurm][:arch] = "el7.centos.x86_64"
default[:slurm][:user][:name] = 'slurm'
default[:slurm][:user][:uid] = 19000
default[:slurm][:user][:gid] = 19000
default[:munge][:user][:name] = 'munge'
default[:munge][:user][:uid] = 19001
default[:munge][:user][:gid] = 19001
