#
# Cookbook Name:: slurm
# Recipe:: execute
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

if node[:slurm][:ensure_waagent_monitor_hostname] then
  execute 'ensure hostname monitoring' do
    command 'sed -i s/Provisioning.MonitorHostName=n/Provisioning.MonitorHostName=y/g  /etc/waagent.conf && systemctl restart walinuxagent'
    only_if "grep -Eq '^Provisioning.MonitorHostName=n$' /etc/waagent.conf" 
  end
end

nodename = node[:cyclecloud][:node][:name]
dns_suffix = node[:slurm][:node_domain_suffix]
if !dns_suffix.nil? && !dns_suffix.empty? && dns_suffix[0] != "." then
  dns_suffix = "." + dns_suffix
end

autoscale_dir = node[:slurm][:autoscale_dir]

directory "#{autoscale_dir}" do
  user "root"
  group "root"
  recursive true
end


filenames = ["slurm_healthcheck.py", "healthcheck.logging.conf"]
filenames.each do |filename| 
    cookbook_file "#{autoscale_dir}/#{filename}" do
        source "#{filename}"
        mode "0644"
        owner "root"
        group "root"
        not_if { ::File.exist?("#{node[:cyclecloud][:bootstrap]}/slurm/#{filename}")}
    end
end

if node[:slurm][:use_nodename_as_hostname] then
  execute 'set hostname' do
    command "hostnamectl set-hostname #{nodename}#{dns_suffix}"
    creates '/etc/slurm.hostname.#{nodename}.enabled'
  end
end

include_recipe "slurm::default"
require 'chef/mixin/shell_out'

slurmuser = node[:slurm][:user][:name]

remote_file '/etc/munge/munge.key' do
  source 'file:///sched/munge/munge.key'
  owner 'munge'
  group 'munge'
  mode '0700'
  action :create
end

link '/etc/slurm/slurm.conf' do
  to '/sched/slurm.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/cyclecloud.conf' do
  to '/sched/cyclecloud.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/cgroup.conf' do
  to '/sched/cgroup.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/topology.conf' do
  to '/sched/topology.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
end

link '/etc/slurm/gres.conf' do
  to '/sched/gres.conf'
  owner "#{slurmuser}"
  group "#{slurmuser}"
  only_if { ::File.exist?('/sched/gres.conf') }
end


defer_block "Defer starting slurmd until end of converge" do
  slurmd_sysconfig="SLURMD_OPTIONS=-N #{nodename}"

  cmd_str = "getent hosts #{node[:cyclecloud][:instance][:ipv4]} | grep -q #{nodename}"
  cmd = Mixlib::ShellOut.new(cmd_str)
  cmd.run_command
  if !cmd.exitstatus.zero?
    raise "Hostname has not registered in DNS yet."
  end

  cmd_str = "hostname | grep -q #{nodename}"
  cmd = Mixlib::ShellOut.new(cmd_str)
  cmd.run_command
  if !cmd.exitstatus.zero?
    raise "Hostname has not registered locally yet."
  end

  myplatform=node[:platform]
  case myplatform
  when 'ubuntu'
    directory '/etc/sysconfig' do
      action :create
    end
    
    file '/etc/sysconfig/slurmd' do
      content slurmd_sysconfig
      mode '0700'
      owner 'slurm'
      group 'slurm'
    end
  when 'centos', 'rhel', 'redhat'
    file '/etc/sysconfig/slurmd' do
      content slurmd_sysconfig
      mode '0700'
      owner 'slurm'
      group 'slurm'
    end
  end

  service 'slurmd' do
    action [:enable, :start]
  end

  service 'munge' do
    action [:enable, :restart]
  end

  # Re-enable a host the first time it converges in the event it was drained
  # set the ip as nodeaddr and hostname in slurm
  execute 'set node to active' do
    # no longer set hostname/nodeaddr. cyclecloud_slurm.py on the slurmctld host will do this.
    command "scontrol update nodename=#{nodename} state=UNDRAIN && touch /etc/slurm.reenabled"
    creates '/etc/slurm.reenabled'
  end
end
