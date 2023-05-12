#
# Cookbook:: slurm
# Recipe:: accounting
#
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
slurmver = node[:slurm][:version]
slurmsemver = node[:slurm][:version].split('-')[0]
slurmsemver_major = slurmsemver.split('.')[0]
slurmsemver_minor = slurmsemver.split('.')[1]

slurmarch = node[:slurm][:arch]
slurmuser = node[:slurm][:user][:name]
clustername = node[:cyclecloud][:cluster][:name]

if !node[:slurm][:accounting][:enabled] 
    return
end 
# Install slurmdbd
myplatformfamily=node[:platform_family]
case myplatformfamily
when 'ubuntu', 'debian'
    slurmdbdpackage = "slurm-slurmdbd_#{slurmver}_amd64.deb"

    #Install for compatibility on Ubuntu
    package 'Install libmariadbclient-dev-compat' do
        package_name 'libmariadbclient-dev-compat'
    end

    package 'Install libssl-dev' do
        package_name 'libssl-dev'
    end

    link '/usr/lib/x86_64-linux-gnu/libssl.so.10' do 
        to '/usr/lib/x86_64-linux-gnu/libssl.so'
    end

    link '/usr/lib/x86_64-linux-gnu/libcrypto.so.10' do 
        to '/usr/lib/x86_64-linux-gnu/libcrypto.so'
    end

    link '/usr/lib/x86_64-linux-gnu/libmysqlclient.so.18' do
        to '/usr/lib/x86_64-linux-gnu/libmysqlclient.so'
    end

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

when 'suse'

    packages = ['mariadb', "slurm_#{slurmsemver_major}_#{slurmsemver_minor}-slurmdbd"]

    package packages do
        action :install
    end
end

# start mariadb
case myplatformfamily
when 'suse'
    service 'mariadb' do
        action [:enable, :start]
    end
end

# create mariadb db and user
createdbcommand = "CREATE DATABASE IF NOT EXISTS slurm_acct_db;"
createusercommand = "CREATE USER IF NOT EXISTS \'#{node[:slurm][:accounting][:user]}\'@\'#{node[:slurm][:accounting][:url]}\' IDENTIFIED BY \'#{node[:slurm][:accounting][:password]}\';"
grantcommand = "GRANT ALL ON slurm_acct_db.* TO \'#{node[:slurm][:accounting][:user]}\'@\'#{node[:slurm][:accounting][:url]}\';"

case myplatformfamily
when 'suse'
    bash 'create slurmdbd user/database for mariadb' do
        code <<-EOH
             mysql -u root -e"#{createdbcommand} #{createusercommand} #{grantcommand}"
             EOH
    end
end

# Configure slurmdbd.conf
template '/sched/slurmdbd.conf' do
    owner "#{slurmuser}"
    source "slurmdbd.conf.erb"
    action :create
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
    source node[:slurm][:accounting][:certificate_url]
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
