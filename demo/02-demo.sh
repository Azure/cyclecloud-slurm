#!/usr/bin/env bash
set -e

. ~/./demo_vars.sh

sudo dnf install -y nfs-utils

echo setting up NFS

##############################################
## Setup NFS
sudo mkdir -p /mnt/exports/sched
sudo mkdir -p /mnt/exports/shared
sudo ln -sf /mnt/exports/sched /
sudo ln -sf /mnt/exports/shared /
sudo chmod -R 777 /mnt/exports

sudo cat >exports <<EOF
/mnt/exports/sched *(rw,sync,no_root_squash)
/mnt/exports/shared *(rw,sync,no_root_squash)
EOF
sudo mv exports /etc/
sudo systemctl restart nfs-mountd

if [ "$1" == "nfsonly" ]; then 
  exit 0
fi
sudo dnf install -y docker gcc java

##############################################
## install swagger-codegen
sudo wget -O /usr/lib/swagger-codegen-cli-2.2.1.jar https://oss.sonatype.org/content/repositories/releases/io/swagger/swagger-codegen-cli/2.2.1/swagger-codegen-cli-2.2.1.jar
cat > swagger-codegen <<EOF
#!/usr/bin/env bash
java -jar /usr/lib/swagger-codegen-cli-2.2.1.jar \$@
EOF

chmod +x swagger-codegen
sudo mv swagger-codegen /usr/bin/

##############################################
## clone and build scalelib
rm -rf $DEMO_ROOT
mkdir -p $DEMO_ROOT
cd $DEMO_ROOT
git clone https://github.com/Azure/cyclecloud-scalelib.git
cd cyclecloud-scalelib
git checkout $DEMO_BRANCH
python3 -m venv ~/.virtualenvs/csdemo
source ~/.virtualenvs/csdemo/bin/activate
pip install --upgrade pip
pip install -r dev-requirements.txt
python setup.py swagger
cd clusters/
python setup.py sdist
cd ../
python setup.py sdist

##############################################
## clone and build azure-slurm
cd $DEMO_ROOT
git clone https://github.com/Azure/cyclecloud-slurm.git
cd cyclecloud-slurm
git checkout $DEMO_BRANCH
pip install -r dev-requirements.txt
mkdir -p libs/
mv ../cyclecloud-scalelib/dist/*.gz libs/
mv ../cyclecloud-scalelib/clusters/dist/*.gz libs/

cd slurm
python setup.py sdist
mv dist/*.gz ../libs/

cd ..
new_scalelib=$(ls -1 $DEMO_ROOT/cyclecloud-slurm/libs/*scalelib* | head -n 1)
new_swagger=$(ls -1t $DEMO_ROOT/cyclecloud-slurm/libs/*swagger* | head -n 1)
python package.py --scalelib $new_scalelib --swagger $new_swagger

## build blobs
./docker-rpmbuild.sh

cd slurm/install
python package.py
##############################################
## stage to /sched

cp $DEMO_ROOT/cyclecloud-slurm/dist/azure-slurm-pkg-3.0.0.tar.gz /sched/
cp $DEMO_ROOT/cyclecloud-slurm/slurm/install.dist/azure-slurm-pkg-3.0.0.tar.gz /sched/
