# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
default[:slurm][:autoscale_version] = "4.0.3"
default[:slurm][:version] = "23.11.9-1"
default[:slurm][:user][:name] = 'slurm'
default[:slurm][:cyclecloud_api] = "cyclecloud_api-8.4.1-py2.py3-none-any.whl"
default[:slurm][:autoscale_dir] = "/opt/azurehpc/slurm"
default[:slurm][:autoscale_pkg] = "azure-slurm-pkg-#{default[:slurm][:autoscale_version]}.tar.gz"
default[:slurm][:install_pkg] = "azure-slurm-install-pkg-#{default[:slurm][:autoscale_version]}.tar.gz"
default[:slurm][:install] = true
default[:slurm][:use_nodename_as_hostname] = false
default[:cyclecloud][:hosts][:simple_vpc_dns][:enabled] = false
default[:cyclecloud][:hosts][:standalone_dns][:enabled] = false
default[:slurm][:additional][:config] = ""
default[:slurm][:ensure_waagent_monitor_hostname] = true

# WORKAROUND: This should not need to be set here, but unexpectedly the default is sometimes being set
# back to /home.
default[:cuser][:base_home_dir] = "/shared/home"

myplatform=node[:platform_family]
case myplatform
when 'ubuntu', 'debian'
  default[:slurm][:arch] = "amd64"
  default[:slurm][:user][:uid] = 64030
  default[:slurm][:user][:gid] = 64030
when 'centos', 'rhel', 'redhat', 'almalinux', 'suse'
  if node[:platform_version] < "8";
    default[:slurm][:arch] = "el7.x86_64"
  else
    default[:slurm][:arch] = "el8.x86_64"
  end
  default[:slurm][:user][:uid] = 11100
  default[:slurm][:user][:gid] = 11100
end
default[:munge][:user][:name] = 'munge'
default[:munge][:user][:uid] = 11101
default[:munge][:user][:gid] = 11101
# Time between a suspend call and when that node can be used again - i.e. 10 minutes to shutdown 
default[:slurm][:suspend_timeout] = 600
# Boot timeout
default[:slurm][:resume_timeout] = 1800

default[:slurm][:accounting][:enabled] = false
default[:slurm][:accounting][:url] = 'localhost'

default[:slurm][:ha_enabled] = false
