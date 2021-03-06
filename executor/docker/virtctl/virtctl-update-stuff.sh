#!/usr/bin/env bash
##############################################################
##
##      Copyright (2019, ) Institute of Software
##          Chinese Academy of Sciences
##             Author: wuheng@otcaix.iscas.ac.cn
##
################################################################

#SHELL_FOLDER=$(cd "$(dirname "$0")";pwd)
#cd $SHELL_FOLDER
#rm -rf dist/ build/ vmm.spec
#pyinstaller -F vmm.py -p ./
#chmod +x dist/vmm
#cp -f dist/vmm /usr/bin

# update config file
echo "+++ Processing: update config file"
cp -f /home/kubevmm/bin/config /etc/kubevmm/config.new
rm -f /etc/kubevmm/config
mv -f /etc/kubevmm/config.new /etc/kubevmm/config
echo "--- Done: update config file"
# update VERSION file
echo "+++ Processing: update VERSION file"
cp -f /home/kubevmm/bin/VERSION /etc/kubevmm/VERSION.new
rm -f /etc/kubevmm/VERSION
mv -f /etc/kubevmm/VERSION.new /etc/kubevmm/VERSION
echo "--- Done: update VERSION file"
# update yamls file
echo "+++ Processing: update yamls file"
cp -rf /home/kubevmm/bin/yamls /etc/kubevmm/yamls.new
rm -rf /etc/kubevmm/yamls
mv -f /etc/kubevmm/yamls.new /etc/kubevmm/yamls
echo "--- Done: update yamls file"
# update kubevmm-adm
echo "+++ Processing: update kubevmm-adm"
cp -f /home/kubevmm/bin/kubevmm-adm /usr/bin/kubevmm-adm.new
rm -f /usr/bin/kubevmm-adm
mv -f /usr/bin/kubevmm-adm.new /usr/bin/kubevmm-adm
echo "--- Done: update kubevmm-adm"
# update kubeovn-adm
echo "+++ Processing: update kubeovn-adm"
cp -f /home/kubevmm/bin/kubeovn-adm /usr/bin/kubeovn-adm.new
rm -f /usr/bin/kubeovn-adm
mv -f /usr/bin/kubeovn-adm.new /usr/bin/kubeovn-adm
chmod +x /usr/bin/kubeovn-adm
echo "--- Done: update kubeovn-adm"
# update kubeovn-adm
echo "+++ Processing: update kubeovn-adm"
cp -f /home/kubevmm/bin/kubeovn-adm /usr/bin/kubeovn-adm.new
rm -f /usr/bin/kubeovn-adm
mv -f /usr/bin/kubeovn-adm.new /usr/bin/kubeovn-adm
chmod +x /usr/bin/kubeovn-adm
echo "--- Done: update kubeovn-adm"
# update kubevirt-ctl
echo "+++ Processing: update kubevirt-ctl"
cp -f /home/kubevmm/bin/kubevirt-ctl /usr/bin/kubevirt-ctl.new
rm -f /usr/bin/kubevirt-ctl
mv -f /usr/bin/kubevirt-ctl.new /usr/bin/kubevirt-ctl
chmod +x /usr/bin/kubevirt-ctl
echo "--- Done: update kubevirt-ctl"
# update device-passthrough
echo "+++ Processing: update device-passthrough"
cp -f /home/kubevmm/bin/device-passthrough /usr/bin/device-passthrough.new
rm -f /usr/bin/device-passthrough
mv -f /usr/bin/device-passthrough.new /usr/bin/device-passthrough
chmod +x /usr/bin/device-passthrough
echo "--- Done: update device-passthrough"
# update vmm
echo "+++ Processing: update vmm"
cp -f /home/kubevmm/bin/vmm /usr/bin/vmm.new
rm -f /usr/bin/vmm
mv -f /usr/bin/vmm.new /usr/bin/vmm
echo "--- Done: update vmm"
# update virt-monitor
echo "+++ Processing: update virt-monitor"
cp -f /home/kubevmm/bin/virt-monitor /usr/bin/virt-monitor.new
rm -f /usr/bin/virt-monitor
mv -f /usr/bin/virt-monitor.new /usr/bin/virt-monitor
echo "--- Done: update virt-monitor"
# update libvirt-event-handler
echo "+++ Processing: update libvirt-event-handler"
cp -f /home/kubevmm/bin/libvirt-event-handler /usr/bin/libvirt-event-handler.new
rm -f /usr/bin/libvirt-event-handler
mv -f /usr/bin/libvirt-event-handler.new /usr/bin/libvirt-event-handler
echo "--- Done: update libvirt-event-handler"
# update kubesds-adm
echo "+++ Processing: update kubesds-adm"
cp -f /home/kubevmm/bin/kubesds-adm /usr/bin/kubesds-adm.new
rm -f /usr/bin/kubesds-adm
mv -f /usr/bin/kubesds-adm.new /usr/bin/kubesds-adm
echo "--- Done: update kubesds-adm"
# update kubesds-rpc-service
echo "+++ Processing: update kubesds-rpc-service"
cp -f /home/kubevmm/bin/kubesds-rpc-service /usr/bin/kubesds-rpc-service.new
rm -f /usr/bin/kubesds-rpc-service
mv -f /usr/bin/kubesds-rpc-service.new /usr/bin/kubesds-rpc-service
echo "--- Done: update kubesds-rpc-service"
# apply kubevirtResource.yaml
if [ -f "/etc/kubevmm/yamls/kubevirtResource.yaml" ];then
	echo "+++ Processing: apply new kubevirtResource.yaml"
	kubectl apply -f /etc/kubevmm/yamls/cloudplus/kubevirtResource.yaml
	echo "--- Done: apply new kubevirtResource.yaml"
else
	echo "*** Warning: apply new kubevirtResource.yaml failed!"
	echo "*** Warning: file /etc/kubevmm/yamls/kubevirtResource.yaml not exists!"
fi
# run virtctl service
echo "Now starting virtctl service..."
python virtctl_in_docker.py