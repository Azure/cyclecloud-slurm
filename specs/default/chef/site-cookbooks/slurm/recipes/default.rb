#
# Cookbook:: slurm
# Recipe:: default
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

slurmver = node[:slurm][:version]
slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]
mungeuser = node[:munge][:user][:name]

# Set up users for Slurm and Munge
group slurmuser do
  gid node[:slurm][:user][:gid]
  not_if "getent group #{slurmuser}"  
end

user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  uid node[:slurm][:user][:uid]
  gid node[:slurm][:user][:gid]
  action :create
end


group mungeuser do
  gid node[:munge][:user][:gid]
  not_if "getent group #{mungeuser}"  
end

user mungeuser do
  comment 'User to run munged'
  shell '/bin/false'
  uid node[:munge][:user][:uid]
  gid node[:munge][:user][:gid]
  action :create
end


myplatform=node[:platform]
case myplatform
when 'ubuntu'

  log "Package munge already installed" do
    only_if "rpm -q munge"
  end
  log "Package munge NOT installed" do
    not_if "rpm -q munge"
  end
  
  package 'Install munge' do
    package_name 'munge'
    not_if "dpkg -l | grep -q munge"
  end
  slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmctld slurm-slurmd slurm-torque slurm-openlava]
  slurmrpms.each do |slurmpkg|
    log "Package #{slurmpkg} already installed" do
      only_if "dpkg -l | grep -q #{slurmpkg}"
    end
    log "Package #{slurmpkg} NOT installed" do
      not_if "dpkg -l | grep -q #{slurmpkg}"
    end
  end
    
  slurmrpms.each do |slurmpkg|
    jetpack_download "#{slurmpkg}_#{slurmver}_amd64.deb" do
      project "slurm"
      not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmpkg}_#{slurmver}_#{slurmarch}.deb") }
      not_if "dpkg -l | grep -q #{slurmpkg}"
    end
  end

  slurmrpms.each do |slurmpkg|
    execute "Install #{slurmpkg}_#{slurmver}_amd64.deb" do
      command "apt install -y #{node[:jetpack][:downloads]}/#{slurmpkg}_#{slurmver}_#{slurmarch}.deb"
      action :run
      not_if { ::File.exist?("/var/spool/slurmd") }
      not_if "dpkg -l | grep -q #{slurmpkg}"
    end
  end

  # Need to manually create links for libraries the RPMs are linked to
  link '/usr/lib/x86_64-linux-gnu/libreadline.so.6' do
    to '/lib/x86_64-linux-gnu/libreadline.so.7'
  end

  link '/usr/lib/x86_64-linux-gnu/libhistory.so.6' do
    to '/lib/x86_64-linux-gnu/libhistory.so.7'
  end

  link '/usr/lib/x86_64-linux-gnu/libncurses.so.5' do
    to '/lib/x86_64-linux-gnu/libncurses.so.5'
  end

  link '/usr/lib/x86_64-linux-gnu/libtinfo.so.5' do
    to '/lib/x86_64-linux-gnu/libtinfo.so.5'
  end

  # file '/etc/ld.so.conf.d/slurmlibs.conf' do
  #   content "/usr/lib/x86_64-linux-gnu/"
  #   action :create_if_missing
  # end



when 'centos'
  slurmrpms = %w[slurm slurm-devel slurm-example-configs slurm-slurmctld slurm-slurmd slurm-perlapi slurm-torque slurm-openlava]

  slurmrpms.each do |slurmpkg|
    log "Package #{slurmpkg} already installed" do
      only_if "rpm -q #{slurmpkg}"
    end
    log "Package #{slurmpkg} NOT installed" do
      not_if "rpm -q #{slurmpkg}"
    end
  end
  
  slurmrpms.each do |slurmpkg|
    jetpack_download "#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
      project "slurm"
      not_if { ::File.exist?("#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm") }
      not_if "rpm -q #{slurmpkg}"
    end
  end

  slurmrpms.each do |slurmpkg|
    package "#{node[:jetpack][:downloads]}/#{slurmpkg}-#{slurmver}.#{slurmarch}.rpm" do
      action :install
      not_if "rpm -q #{slurmpkg}"
    end
  end
end

#Fix munge permissions and create key
directory "/etc/munge" do
  owner mungeuser
  group mungeuser
  mode 0700
end
directory "/var/lib/munge" do
  owner mungeuser
  group mungeuser
  mode 0711
end
directory "/var/log/munge" do
  owner mungeuser
  group mungeuser
  mode 0700
end
directory "/run/munge" do
  owner mungeuser
  group mungeuser
  mode 0755
end

directory "/sched/munge" do
  owner mungeuser
  group mungeuser
  mode 0700
end

# Set up slurm 
user slurmuser do
  comment 'User to run slurmd'
  shell '/bin/false'
  action :create
end

# add slurm to cyclecloud so it has access to jetpack / userdata
group 'cyclecloud' do
    members [slurmuser]
    append true
    action :modify
end    

directory '/var/spool/slurmd' do
  owner slurmuser
  action :create
end
  
directory '/var/log/slurmd' do
  owner slurmuser
  action :create
end

directory '/var/log/slurmctld' do
  owner slurmuser
  action :create
end
