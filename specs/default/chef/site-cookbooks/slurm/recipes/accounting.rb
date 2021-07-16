#
# Cookbook:: slurm
# Recipe:: accounting
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]
clustername = node[:cyclecloud][:cluster][:name]

if !node[:slurm][:accounting][:enabled] 
    return
end 
# Install slurmdbd
myplatform=node[:platform]
case myplatform
when 'ubuntu'
    slurmdbdpackage = "slurm-slurmdbd_#{slurmver}_amd64.deb"
    jetpack_download "#{slurmdbdpackage}" do
        project "slurm"
        not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmdbdpackage}") }
    end

    execute "Install #{slurmdbdpackage}" do
        command "apt install -y #{node[:jetpack][:downloads]}/#{slurmdbdpackage}"
        action :run
        not_if { ::File.exist?("/var/spool/slurmdbd") }
    end

when 'centos', 'rhel', 'redhat'
    slurmdbdpackage = "slurm-slurmdbd-#{slurmver}.#{slurmarch}.rpm"
    jetpack_download "#{slurmdbdpackage}" do
        project "slurm"
        not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmdbdpackage}") }
    end

    package "#{node[:jetpack][:downloads]}/#{slurmdbdpackage}" do
        action :install
    end
end

# Configure slurmdbd.conf
template '/sched/slurmdbd.conf' do
    owner "#{slurmuser}"
    source "slurmdbd.conf.erb"
    action :create_if_missing
    mode 0600
    variables lazy {{
        :accountdb => node[:slurm][:accounting][:url],
        :dbuser => node[:slurm][:accounting][:user],
        :dbpass => node[:slurm][:accounting][:password],
        :slurmver => slurmver
    }}
end

# Link shared slurmdbd.conf to real config file location
link '/etc/slurm/slurmdbd.conf' do
    to '/sched/slurmdbd.conf'
    owner "#{slurmuser}"
    group "#{slurmuser}"
end

remote_file '/etc/slurm/BaltimoreCyberTrustRoot.crt.pem' do
    source 'https://www.digicert.com/CACerts/BaltimoreCyberTrustRoot.crt.pem'
    owner 'slurm'
    group 'slurm'
    mode 0644
end

# Start slurmdbd service
#defer_block "Defer starting slurmdbd until end of converge" do
service 'slurmdbd' do
    action [:enable, :restart]
end

bash 'Add cluster to slurmdbd' do
    code <<-EOH
        sacctmgr -i add cluster #{clustername} && touch /etc/slurmdbd.configured 
        EOH
    not_if { ::File.exist?('/etc/slurmdbd.configured') }
    not_if "sleep 5 && sacctmgr show cluster -p | grep -i #{clustername}" 
end

#end
