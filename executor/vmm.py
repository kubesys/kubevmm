'''
Copyright (2019, ) Institute of Software, Chinese Academy of 

@author: wuheng@otcaix.iscas.ac.cn
@author: wuyuewen@otcaix.iscas.ac.cn
'''

from kubernetes import config, client
from kubernetes.client import V1DeleteOptions
from json import loads
from json import dumps, dump
import sys
import os
import time
import json
import subprocess
import ConfigParser
import traceback
import shutil
from xml.etree.ElementTree import fromstring

from xmljson import badgerfish as bf

from kubernetes.client.rest import ApiException

from utils.cmdrpc import rpcCallWithResult
from utils.libvirt_util import check_pool_content_type, refresh_pool, get_vol_info_by_qemu, get_volume_xml, get_pool_path, is_volume_in_use, is_volume_exists, get_volume_current_path, vm_state, is_vm_exists, is_vm_active, get_boot_disk_path, get_xml, undefine_with_snapshot, undefine, define_xml_str
from utils.utils import delete_custom_object, create_custom_object, get_custom_object, update_custom_object, get_rebase_backing_file_cmds, add_spec_in_volume, get_hostname_in_lower_case, DiskImageHelper, updateDescription, get_volume_snapshots, updateJsonRemoveLifecycle, addSnapshots, report_failure, addPowerStatusMessage, RotatingOperation, ExecuteException, string_switch, deleteLifecycleInJson
from utils import logger

class parser(ConfigParser.ConfigParser):  
    def __init__(self,defaults=None):  
        ConfigParser.ConfigParser.__init__(self,defaults=None)  
    def optionxform(self, optionstr):  
        return optionstr 

cfg = "/etc/kubevmm/config"
if not os.path.exists(cfg):
    cfg = "/home/kubevmm/bin/config"
config_raw = parser()
config_raw.read(cfg)

VM_PLURAL = config_raw.get('VirtualMachine', 'plural')
VMI_PLURAL = config_raw.get('VirtualMachineImage', 'plural')
VERSION = config_raw.get('VirtualMachine', 'version')
GROUP = config_raw.get('VirtualMachine', 'group')
VMI_KIND = 'VirtualMachineImage'
VMDI_KIND = 'VirtualMachineDiskImage'
VMD_KIND = 'VirtualMachineDisk'
VMDI_PLURAL = config_raw.get('VirtualMachineDiskImage', 'plural')
VMDI_VERSION = config_raw.get('VirtualMachineDiskImage', 'version')
VMDI_GROUP = config_raw.get('VirtualMachineDiskImage', 'group')
VMD_PLURAL = config_raw.get('VirtualMachineDisk', 'plural')
VMD_VERSION = config_raw.get('VirtualMachineDisk', 'version')
VMD_GROUP = config_raw.get('VirtualMachineDisk', 'group')
DEFAULT_TEMPLATE_DIR = config_raw.get('DefaultTemplateDir', 'default')
DEFAULT_VMD_TEMPLATE_DIR = config_raw.get('DefaultVirtualMachineDiskTemplateDir', 'vmdi')
DEFAULT_DEVICE_DIR = config_raw.get('DefaultDeviceDir', 'default')

HOSTNAME = get_hostname_in_lower_case()

LOG = '/var/log/virtctl.log'
logger = logger.set_logger(os.path.basename(__file__), LOG)


'''
A atomic operation: Convert vm to image.
'''
def create_vm_image_from_vm(name, domain, targetPool):
    # cmd = os.path.split(os.path.realpath(__file__))[0] +'/scripts/convert-vm-to-image.sh ' + name
    
    '''
    A list to record what we already done.
    '''
    done_operations = []
    doing = ''
    
    class step_1_dumpxml_to_path(RotatingOperation):
        
        def __init__(self, vmi, domain, targetPool, tag):
            self.tag = tag
            self.vmi = vmi
            self.domain = domain
            self.temp_path = '%s/%s/%s.xml.new' % (get_pool_path(targetPool), vmi)
            self.path = '%s/%s/%s.xml' % (get_pool_path(targetPool), vmi, vmi)
    
        def option(self):
            if os.path.exists(self.path):
                raise Exception('409, Conflict. File %s already exists, aborting copy.' % self.path)
            vm_xml = get_xml(self.domain)
            with open(self.temp_path, 'w') as fw:
                fw.write(vm_xml)
            shutil.move(self.temp_path, self.path)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                if os.path.exists(self.path):
                    os.remove(self.path)
            return 
        
    class step_2_copy_template_to_path(RotatingOperation):
        
        def __init__(self, vmi, domain, targetPool, tag, full_copy=True):
            self.tag = tag
            self.vmi = vmi
            self.domain = domain
            self.full_copy = full_copy
            self.source_path = get_boot_disk_path(domain)
            self.dest_dir = '%s/%s' % (get_pool_path(targetPool), vmi)
            self.dest_path = '%s/%s' % (self.dest_dir, vmi)
#             self.store_source_path = '%s/%s.path' % (DEFAULT_TEMPLATE_DIR, vmi)
            self.xml_path = '%s/%s.xml' % (self.dest_dir, vmi)
    
        def option(self):
            
            '''
            Copy template's boot disk to destination dir.
            '''
            if self.full_copy:
                copy_template_cmd = 'cp -f %s %s' % (self.source_path, self.dest_path)
            runCmd(copy_template_cmd)
            
            cmd1 = 'qemu-img rebase -f qcow2 %s -b "" -u' % (self.dest_path)
            runCmd(cmd1)
            
            '''
            Store source path of template's boot disk to .path file.
            '''
#             with open(self.store_source_path, 'w') as fw:
#                 fw.write(self.source_path)
                
            config = {}
            config['name'] = self.vmi
            config['dir'] = self.dest_dir
            config['current'] = self.dest_path
        
            with open(self.dest_dir + '/config.json', "w") as f:
                dump(config, f)
                
            '''
            Replate template's boot disk to dest path in .xml file.
            '''
            string_switch(self.xml_path, self.source_path, self.dest_path, 1)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                if os.path.exists(self.dest_dir):
                    runCmd('rm -rf %s' %(self.dest_dir))
            return 

    class step_3_undefine_vm(RotatingOperation):
        
        def __init__(self, vm, tag, force=True):
            self.tag = tag
            self.vm = vm
            self.force = force
            self.tmp_path = '/tmp/%s.xml' % (vm)
    
        def option(self):
            vm_xml = get_xml(self.vm)
            with open(self.tmp_path, 'w') as fw:
                fw.write(vm_xml)
            file_path1 = '%s/%s-nic-*' % (DEFAULT_DEVICE_DIR, self.vm)
            file_path2 = '%s/%s-disk-*' % (DEFAULT_DEVICE_DIR, self.vm)
            cmd = 'mv -f %s %s %s' % (file_path1, file_path2, DEFAULT_TEMPLATE_DIR)
            try:
                runCmd(cmd)
            except:
                logger.warning('Oops! ', exc_info=1)
            try:
                if self.force:
                    undefine_with_snapshot(self.vm)
                else:
                    undefine(self.vm)
            except:
                if is_vm_exists(self.vm):
                    raise Exception('VM %s undefine failed!' % self.vm)
                logger.warning('Oops! ', exc_info=1)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                with open(self.tmp_path, 'r') as fr:
                    vm_xml = fr.read()
                define_xml_str(vm_xml)
            file_path1 = '%s/%s-nic-*' % (DEFAULT_TEMPLATE_DIR, self.vm)
            file_path2 = '%s/%s-disk-*' % (DEFAULT_TEMPLATE_DIR, self.vm)
            cmd = 'mv -f %s %s %s' % (file_path1, file_path2, DEFAULT_DEVICE_DIR)
            try:
                runCmd(cmd)
            except:
                logger.warning('Oops! ', exc_info=1)
            return 
        
    class final_step_delete_source_file(RotatingOperation):
        
        def __init__(self, vm, tag):
            self.tag = tag
            self.vm = vm
            self.store_source_path = '%s/%s.path' % (DEFAULT_TEMPLATE_DIR, vm)
    
        def option(self):
            '''
            Remove source path of template's boot disk
            '''
            with open(self.store_source_path, 'r') as fr:
                self.source_path = fr.read()
            if os.path.exists(self.source_path):
                os.remove(self.source_path)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                logger.debug('In final step, rotating noting.')
            return 
        
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, name=name)
    '''
    #Preparations
    '''
    doing = 'Preparations'
    if not is_vm_exists(domain):
        raise Exception('VM %s not exists!' % domain)
    if is_vm_active(domain):
        raise Exception('Cannot create vmi from running vm %s.' % domain)
#     if get_boot_disk_path(name) != get_volume_path(sourcePool, sourceVolume):
#         raise Exception('Wrong source pool %s or wrong source volume %s.' % (sourcePool, sourceVolume))
    if not check_pool_content_type(targetPool, 'vmi'):
        raise Exception('Target pool\'s content type is not vmi.')
    dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
    dest = '%s/%s' %(dest_dir, name)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, 0x0711)
    step1 = step_1_dumpxml_to_path(name, domain, targetPool, 'step1')
    step2 = step_2_copy_template_to_path(name, domain, targetPool, 'step2')
#     step3 = step_3_undefine_vm(name, 'step3')
#     step4 = final_step_delete_source_file(name, 'step4')
    try:
        #cmd = 'bash %s/scripts/convert-vm-to-image.sh %s' %(PATH, name)
        '''
        #Step 1: dump VM .xml file to template's path
        '''
        doing = step1.tag
        step1.option()
        '''
        #Step 2: copy template to template's path
        '''       
        doing = step2.tag
        step2.option()
#         doing = step3.tag
#         step3.option()
#         '''
#         #Step 4: synchronize information to Kubernetes
#         '''   
#         doing = 'Synchronize to Kubernetes'       
#         jsonDict = jsonStr.copy()
#         jsonDict['kind'] = 'VirtualMachineImage'
#         jsonDict['metadata']['kind'] = 'VirtualMachineImage'
#         del jsonDict['metadata']['resourceVersion']
#         del jsonDict['spec']['lifecycle']
#         try:
#             client.CustomObjectsApi().create_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, body=jsonDict)
#             client.CustomObjectsApi().delete_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, name=name, body=V1DeleteOptions())
#         except ApiException:
#             logger.warning('Oops! ', exc_info=1)
        write_result_to_server(name, 'create', VMD_KIND, VMD_PLURAL,  {'current': dest, 'pool': targetPool})
#         write_result_to_server(name, 'create', VMI_KIND, VMI_PLURAL, {'pool': targetPool})
#         '''
#         #Check sychronization in Virtlet.
#           timeout = 3s
#         '''
#         i = 0
#         success = False
#         while(i < 3):
#             try: 
#                 client.CustomObjectsApi().get_namespaced_custom_object(group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, name=name)
#             except:
#                 time.sleep(1)
#                 success = False
#                 continue
#             finally:
#                 i += 1
#             success = True
#             break;
#         if not success:
#             raise Exception('Synchronize information in Virtlet failed, does docker service stopped?')
        
#         '''
#         #Final step: delete source file
#         '''       
#         doing = step4.tag
#         step4.option()
    except:
        logger.debug(done_operations)
        error_reason = 'VmmError'
        error_message = '%s failed!' % doing
        logger.error(error_reason + ' ' + error_message)
        logger.error('Oops! ', exc_info=1)
#         report_failure(name, jsonStr, error_reason, error_message, GROUP, VERSION, VM_PLURAL)
        step2.rotating_option()
        step1.rotating_option()

'''
A atomic operation: Convert image to vm.
'''
def convert_image_to_vm(name):
    '''
    A list to record what we already done.
    '''
    done_operations = []
    doing = ''
    
    class step_1_copy_template_to_path(RotatingOperation):
        
        def __init__(self, vm, tag, full_copy=True):
            self.tag = tag
            self.vm = vm
            self.full_copy = full_copy
            self.source_path = '%s/%s' % (DEFAULT_TEMPLATE_DIR, vm)
            self.store_target_path = '%s/%s.path' % (DEFAULT_TEMPLATE_DIR, vm)
            self.xml_path = '%s/%s.xml' % (DEFAULT_TEMPLATE_DIR, vm)
    
        def option(self):
            '''
            Copy template's boot disk to destination dir.
            '''
            with open(self.store_target_path, 'r') as fr:
                self.dest_path = fr.read()
            if os.path.exists(self.dest_path):
                raise Exception('409, Conflict. File %s already exists, aborting copy.' % self.dest_path)
            if self.full_copy:
                copy_template_cmd = 'cp %s %s' % (self.source_path, self.dest_path)
            runCmd(copy_template_cmd)
            '''
            Replate template's boot disk to dest path in .xml file.
            '''
            string_switch(self.xml_path, self.source_path, self.dest_path, 1)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                with open(self.store_target_path, 'r') as fr:
                    self.dest_path = fr.read()
                if os.path.exists(self.dest_path):
                    os.remove(self.dest_path)
            return 
        
    class step_2_define_vm(RotatingOperation):
        
        def __init__(self, vm, tag):
            self.tag = tag
            self.vm = vm
            self.xml_path = '%s/%s.xml' % (DEFAULT_TEMPLATE_DIR, vm)
    
        def option(self):
            with open(self.xml_path, 'r') as fr:
                vm_xml = fr.read()
            define_xml_str(vm_xml)
            file_path1 = '%s/%s-nic-*' % (DEFAULT_TEMPLATE_DIR, self.vm)
            file_path2 = '%s/%s-disk-*' % (DEFAULT_TEMPLATE_DIR, self.vm)
            cmd = 'mv -f %s %s %s' % (file_path1, file_path2, DEFAULT_DEVICE_DIR)
            try:
                runCmd(cmd)
            except:
                logger.warning('Oops! ', exc_info=1)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                if is_vm_exists(self.vm):
                    undefine(self.vm)
            file_path1 = '%s/%s-nic-*' % (DEFAULT_DEVICE_DIR, self.vm)
            file_path2 = '%s/%s-disk-*' % (DEFAULT_DEVICE_DIR, self.vm)
            cmd = 'mv -f %s %s %s' % (file_path1, file_path2, DEFAULT_TEMPLATE_DIR)
            try:
                runCmd(cmd)
            except:
                logger.warning('Oops! ', exc_info=1)
            return 

    class final_step_delete_source_file(RotatingOperation):
        
        def __init__(self, vm, tag):
            self.tag = tag
            self.vm = vm
            self.source_path = '%s/%s' % (DEFAULT_TEMPLATE_DIR, vm)
            self.store_target_path = '%s/%s.path' % (DEFAULT_TEMPLATE_DIR, vm)
            self.xml_path = '%s/%s.xml' % (DEFAULT_TEMPLATE_DIR, vm)
    
        def option(self):
            '''
            Remove source path of template's boot disk
            '''
            for path in [self.source_path, self.store_target_path, self.xml_path]:
                if os.path.exists(path):
                    os.remove(path)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                logger.debug('In final step, rotating noting.')
            return 
        
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, name=name)
    step1 = step_1_copy_template_to_path(name, 'step1')
    step2 = step_2_define_vm(name, 'step2')
    step3 = final_step_delete_source_file(name, 'step3')
    try:
        '''
        #Step 1: copy template to original path
        '''
        doing = step1.tag
        step1.option()
        '''
        #Step 2: define VM
        '''       
        doing = step2.tag
        step2.option()
#         '''
#         #Step 3: synchronize information to Kubernetes
#         '''  
#         jsonDict = jsonStr.copy()
#         jsonDict['kind'] = 'VirtualMachine'
#         jsonDict['metadata']['kind'] = 'VirtualMachine'
#         del jsonDict['metadata']['resourceVersion']
#         del jsonDict['spec']['lifecycle']
#         try:
#             client.CustomObjectsApi().create_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, body=jsonDict)
#             client.CustomObjectsApi().delete_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, name=name, body=V1DeleteOptions())
#         except ApiException:
#             logger.warning('Oops! ', exc_info=1)
        '''
        #Check sychronization in Virtlet.
          timeout = 3s
        '''
        i = 0
        success = False
        while(i < 3):
            try:
                client.CustomObjectsApi().get_namespaced_custom_object(group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, name=name)
            except:
                time.sleep(1)
                success = False
                continue
            finally:
                i += 1
            success = True
            break;
        if not success:
            raise Exception('Synchronize information in Virtlet failed, does docker service stopped?')
        '''
        #Final step: delete source file
        '''       
        doing = step3.tag
        step3.option()
    except:
        logger.debug(done_operations)
        error_reason = 'VmmError'
        error_message = '%s failed!' % doing
        logger.error(error_reason + ' ' + error_message)
        logger.error('Oops! ', exc_info=1)
#         report_failure(name, jsonStr, error_reason, error_message, GROUP, VERSION, VM_PLURAL)
        step3.rotating_option()
        step2.rotating_option()
        step1.rotating_option()

def create_vmdi_from_disk(name, sourceVolume, source, target):
    # cmd = os.path.split(os.path.realpath(__file__))[0] +'/scripts/convert-vm-to-image.sh ' + name
    
    '''
    A list to record what we already done.
    '''
    done_operations = []
    doing = ''
    
#     class step_1_dumpxml_to_path(RotatingOperation):
#         
#         def __init__(self, vmd, sourcePool, tag):
#             self.tag = tag
#             self.vmd = vmd
#             self.sourcePool = sourcePool
#             self.temp_path = '%s/%s.xml.new' % (DEFAULT_VMD_TEMPLATE_DIR, vmd)
#             self.path = '%s/%s.xml' % (DEFAULT_VMD_TEMPLATE_DIR, vmd)
#     
#         def option(self):
#             vmd_xml = get_volume_xml(self.sourcePool, self.vmd)
#             with open(self.temp_path, 'w') as fw:
#                 fw.write(vmd_xml)
#             shutil.move(self.temp_path, self.path)
#             done_operations.append(self.tag)
#             return 
#     
#         def rotating_option(self):
#             if self.tag in done_operations:
#                 if os.path.exists(self.path):
#                     os.remove(self.path)
#             return 
    
    class step_1_copy_template_to_path(RotatingOperation):
        
        def __init__(self, name, vmd, sourcePool, targetPool, tag, full_copy=True):
            self.tag = tag
            self.name = name
            self.vmd = vmd
            self.pool = sourcePool
            self.full_copy = full_copy
            self.source_dir = '%s/%s' % (get_pool_path(sourcePool), vmd)
            self.dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
            self.dest = '%s/%s' % (self.dest_dir, name)
            self.source_config_file = '%s/config.json' % (self.source_dir)
            self.target_config_file = '%s/config.json' % (self.dest_dir)
#             self.store_source_path = '%s/%s.path' % (DEFAULT_VMD_TEMPLATE_DIR, vmd)
#             self.xml_path = '%s/%s.xml' % (DEFAULT_VMD_TEMPLATE_DIR, vmd)
    
        def option(self):
            '''
            Copy template's boot disk to destination dir.
            '''
            if os.path.exists(self.target_config_file):
                raise Exception('409, Conflict. Resource %s already exists, aborting copy.' % self.target_config_file)
#             set_backing_file_cmd = get_rebase_backing_file_cmds(self.source_dir, self.dest_dir)
            source_current = _get_current(self.source_config_file)
            
            if self.full_copy:
                copy_template_cmd = 'cp -f %s %s' % (source_current, self.dest)
            runCmd(copy_template_cmd)
            
            cmd1 = 'qemu-img rebase -f qcow2 %s -b "" -u' % (self.dest)
            runCmd(cmd1)
            
#             for cmd in set_backing_file_cmd:
#                 runCmd(cmd)
            
            config = {}
            config['name'] = self.name
            config['dir'] = self.dest_dir
            config['current'] = self.dest

            with open(self.target_config_file, "w") as f:
                dump(config, f)
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                for path in [self.dest_dir]:
#                 for path in [self.dest_path, self.store_source_path, self.xml_path]:
                    if os.path.exists(path):
                        runCmd('rm -rf %s' %(path))
            return 

    class step_2_delete_source_file(RotatingOperation):
        
        def __init__(self, vmd, sourcePool, tag):
            self.tag = tag
            self.vmd = vmd
            self.source_dir = '%s/%s' % (get_pool_path(sourcePool), vmd)
    
        def option(self):
            '''
            Remove source path of template's boot disk
            '''
            if os.path.exists(self.source_dir):
                runCmd('rm -rf %s' %(self.source_dir))
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                logger.debug('In final step, rotating noting.')
            return 
        
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, name=name)
    '''
    #Preparations
    '''
    sourcePool = get_pool_info_from_k8s(source)['poolname']
    targetPool = get_pool_info_from_k8s(target)['poolname']
    result, data = rpcCallWithResult('kubesds-adm prepareDisk --vol %s' % sourceVolume)
    doing = 'Preparations'
    if not sourcePool:
        raise Exception('404, Not Found. Source pool not found.')
    if not is_volume_exists(sourceVolume, sourcePool):
        raise Exception('VM disk %s not exists!' % sourceVolume)
#     if is_volume_in_use(vol=name, pool=sourcePool):
#         raise Exception('Cannot covert vmd in use to image.')
    if not check_pool_content_type(targetPool, 'vmdi'):
        raise Exception('Target pool\'s content type is not vmdi.')
    dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, 0x0711)
#     step1 = step_1_dumpxml_to_path(name, sourcePool, 'step1')
    step1 = step_1_copy_template_to_path(name, sourceVolume, sourcePool, targetPool, 'step1')
    try:
        #cmd = 'bash %s/scripts/convert-vm-to-image.sh %s' %(PATH, name)
        '''
        #Step 1
        '''
        doing = step1.tag
        step1.option()
#         '''
#         #Step 4: synchronize information to Kubernetes
#         '''   
#         doing = 'Synchronize to Kubernetes'       
#         jsonDict = jsonStr.copy()
#         jsonDict['kind'] = 'VirtualMachineImage'
#         jsonDict['metadata']['kind'] = 'VirtualMachineImage'
#         del jsonDict['metadata']['resourceVersion']
#         del jsonDict['spec']['lifecycle']
#         try:
#             client.CustomObjectsApi().create_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, body=jsonDict)
#             client.CustomObjectsApi().delete_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, name=name, body=V1DeleteOptions())
#         except ApiException:
#             logger.warning('Oops! ', exc_info=1)
#         '''
#         #Check sychronization in Virtlet.
#           timeout = 3s
#         '''
#         i = 0
#         success = False
#         while(i < 3):
#             try: 
#                 client.CustomObjectsApi().get_namespaced_custom_object(group=VMDI_GROUP, version=VMDI_VERSION, namespace='default', plural=VMDI_PLURAL, name=name)
#             except:
#                 time.sleep(1)
#                 success = False
#                 continue
#             finally:
#                 i += 1
#             success = True
#             break;
#         if not success:
#             raise Exception('Synchronize information in Virtlet failed!')
        config_file = '%s/config.json' % (dest_dir)
        current = _get_current(config_file)
        write_result_to_server(name, 'create', VMDI_KIND, VMDI_PLURAL, {'current': current, 'pool': target, 'poolname': targetPool})
#         '''
#         #Step 2
#         '''
#         doing = step2.tag
#         step2.option()
#         write_result_to_server(name, 'delete', VMD_KIND, VMD_PLURAL, {'pool': sourcePool})
    except:
        logger.debug(done_operations)
        error_reason = 'VmmError'
        error_message = '%s failed!' % doing
        logger.error(error_reason + ' ' + error_message)
        logger.error('Oops! ', exc_info=1)
#         report_failure(name, jsonStr, error_reason, error_message, GROUP, VERSION, VM_PLURAL)
        step1.rotating_option()

'''
A atomic operation: Convert image to vm.
'''
def convert_vmdi_to_vmd(name, sourcePool, targetPool):
    '''
    A list to record what we already done.
    '''
    done_operations = []
    doing = ''
    
    class step_1_copy_template_to_path(RotatingOperation):
        
        def __init__(self, vmdi, sourcePool, targetPool, tag, full_copy=True):
            self.tag = tag
            self.vmdi = vmdi
            self.pool = targetPool
            self.full_copy = full_copy
            self.source_dir = '%s/%s' % (get_pool_path(sourcePool), vmdi)
            self.dest_dir = '%s/%s' % (get_pool_path(targetPool), vmdi)
            self.config_file = '%s/config.json' % (self.dest_dir)
#             self.store_target_path = '%s/%s.path' % (DEFAULT_VMD_TEMPLATE_DIR, vmdi)
#             self.xml_path = '%s/%s.xml' % (DEFAULT_VMD_TEMPLATE_DIR, vmdi)
    
        def option(self):
            if not os.path.exists(self.dest_dir):
                os.makedirs(self.dest_dir, 0x0711)
            if os.path.exists(self.config_file):
                raise Exception('409, Conflict. Resource %s already exists, aborting copy.' % self.config_file)
            
            set_backing_file_cmd = get_rebase_backing_file_cmds(self.source_dir, self.dest_dir)
            
            if self.full_copy:
                copy_template_cmd = 'cp -rf %s/* %s' % (self.source_dir, self.dest_dir)
            runCmd(copy_template_cmd)
            
            for cmd in set_backing_file_cmd:
                runCmd(cmd)
                
            current = _get_current(self.config_file).replace(self.source_dir, self.dest_dir)
            config = {}
            config['name'] = self.vmdi
            config['dir'] = self.dest_dir
            config['current'] = current
            with open(self.config_file, "w") as f:
                dump(config, f)
    
        def rotating_option(self):
            if self.tag in done_operations:
                if os.path.exists(self.dest_dir):
                    runCmd('rm -rf %s' %(self.dest_dir))
            return 
        
    class step_2_delete_source_file(RotatingOperation):
        
        def __init__(self, vmdi, sourcePool, tag):
            self.tag = tag
            self.vmdi = vmdi
            self.source_dir = '%s/%s' % (get_pool_path(sourcePool), vmdi)
#             self.store_target_path = '%s/%s.path' % (DEFAULT_VMD_TEMPLATE_DIR, vmdi)
#             self.xml_path = '%s/%s.xml' % (DEFAULT_VMD_TEMPLATE_DIR, vmdi)
    
        def option(self):
            '''
            Remove source path of template's boot disk
            '''
            for path in [self.source_dir]:
                if os.path.exists(path):
                    runCmd('rm -rf %s' %(path))
            done_operations.append(self.tag)
            return 
    
        def rotating_option(self):
            if self.tag in done_operations:
                logger.debug('In final step, rotating noting.')
            return 
        
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, name=name)
    if not sourcePool:
        raise Exception('404, Not Found. Source pool not found.')
    dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
    step1 = step_1_copy_template_to_path(name, sourcePool, targetPool, 'step1')
    step2 = step_2_delete_source_file(name, sourcePool, 'step2')
    try:
        '''
        #Step 1: copy template to original path
        '''
        doing = step1.tag
        step1.option()
#         '''
#         #Step 3: synchronize information to Kubernetes
#         '''  
#         jsonDict = jsonStr.copy()
#         jsonDict['kind'] = 'VirtualMachine'
#         jsonDict['metadata']['kind'] = 'VirtualMachine'
#         del jsonDict['metadata']['resourceVersion']
#         del jsonDict['spec']['lifecycle']
#         try:
#             client.CustomObjectsApi().create_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VM_PLURAL, body=jsonDict)
#             client.CustomObjectsApi().delete_namespaced_custom_object(
#                 group=GROUP, version=VERSION, namespace='default', plural=VMI_PLURAL, name=name, body=V1DeleteOptions())
#         except ApiException:
#             logger.warning('Oops! ', exc_info=1)
        config_file = '%s/config.json' % (dest_dir)
        current = _get_current(config_file)
        write_result_to_server(name, 'create', VMD_KIND, VMD_PLURAL, {'current': current, 'pool': targetPool})
        
        '''
        #Check sychronization in Virtlet.
          timeout = 3s
        '''
        i = 0
        success = False
        while(i < 3):
            try:
                client.CustomObjectsApi().get_namespaced_custom_object(group=VMD_GROUP, version=VMD_VERSION, namespace='default', plural=VMD_PLURAL, name=name)
            except:
                time.sleep(1)
                success = False
                continue
            finally:
                i += 1
            success = True
            break;
        if not success:
            raise Exception('Synchronize information in Virtlet failed!')
        '''
        #Step 2: define VM
        '''       
        doing = step2.tag
        step2.option()
        
        write_result_to_server(name, 'delete', VMDI_KIND, VMDI_PLURAL, {'pool': sourcePool})
    except:
        logger.debug(done_operations)
        error_reason = 'VmmError'
        error_message = '%s failed!' % doing
        logger.error(error_reason + ' ' + error_message)
        logger.error('Oops! ', exc_info=1)
#         report_failure(name, jsonStr, error_reason, error_message, GROUP, VERSION, VM_PLURAL)
        step2.rotating_option()
        step1.rotating_option()
        
def create_vmdi(name, target):
    pool_info = get_pool_info_from_k8s(target)
#     try:
#         result, data = rpcCallWithResult('kubesds-adm prepareDisk --path %s' % source, raise_it=False)
#     except Exception:
#         pass
    targetPool = pool_info['poolname']
    dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
    dest = '%s/%s' % (dest_dir, name)
    if not os.path.exists(dest_dir) or not os.path.isfile(dest):
        raise Exception('404, Not found. Target file %s not exists.' % dest)
#     if not os.path.exists(dest_dir):
#         os.makedirs(dest_dir, 0x0711)
#     if os.path.exists(dest):
#         raise Exception('409, Conflict. File %s already exists, aborting copy.' % dest)
    if not check_pool_content_type(targetPool, 'vmdi'):
        raise Exception('Target pool\'s content type is not vmdi.')
#     cmd = 'cp -f %s %s' % (source, dest)
#     logger.debug(cmd)
#     try:
#         runCmd(cmd)
#     except:
#         if os.path.exists(dest_dir):
#             runCmd('rm -rf %s' % dest_dir)
#         raise Exception('400, Bad Reqeust. Copy %s to %s failed!' % (source, dest))
    retv = None
    cmd0 = 'qemu-img info -U %s | grep "file format" | grep "qcow2"' % (dest)
    try:
        retv = runCmd(cmd0)
    except:
        if os.path.exists(dest_dir):
            runCmd('rm -rf %s' % dest_dir)
        raise Exception('400, Bad Reqeust. Execute "qemu-img info -U %s" failed!' % (dest))
    if retv:
        cmd1 = 'qemu-img rebase -f qcow2 %s -b "" -u' % (dest)
        try:
            runCmd(cmd1)
        except:
            if os.path.exists(dest_dir):
                runCmd('rm -rf %s' % dest_dir)
            raise Exception('400, Bad Reqeust. Execute "qemu-img rebase -f qcow2 %s" failed!' % (dest))
    
    config = {}
    config['name'] = name
    config['dir'] = dest_dir
    config['current'] = dest

    with open(dest_dir + '/config.json', "w") as f:
        dump(config, f)
    
    write_result_to_server(name, 'create', VMDI_KIND, VMDI_PLURAL, {'current': dest, 'pool': target, 'poolname': targetPool})
    
def create_disk_from_vmdi(name, targetPool, source):
    dest_dir = '%s/%s' % (get_pool_path(targetPool), name)
    dest = '%s/%s' % (dest_dir, name)
    dest_config_file = '%s/config.json' % (dest_dir)
    if not os.path.exists(dest_dir):
        os.makedirs(dest_dir, 0x0711)
    if os.path.exists(dest_config_file):
        raise Exception('409, Conflict. Path %s already in use, aborting copy.' % dest_dir)
    cmd = 'cp -f %s %s' % (source, dest)
    try:
        runCmd(cmd)
    except:
        if os.path.exists(dest_dir):
            runCmd('rm -rf %s' % dest_dir)
        raise Exception('400, Bad Reqeust. Copy %s to %s failed!' % (source, dest))
    
    cmd1 = 'qemu-img rebase -f qcow2 %s -b "" -u' % (dest)
    try:
        runCmd(cmd1)
    except:
        if os.path.exists(dest_dir):
            runCmd('rm -rf %s' % dest_dir)
        raise Exception('400, Bad Reqeust. Execute "qemu-img rebase -f qcow2 %s" failed!' % (dest))
    
    config = {}
    config['name'] = name
    config['dir'] = dest_dir
    config['current'] = dest

    with open(dest_dir + '/config.json', "w") as f:
        dump(config, f)
    
    time.sleep(1)
    
    write_result_to_server(name, 'create', VMD_KIND, VMD_PLURAL,  {'current': dest, 'pool': targetPool})

# def toImage(name):
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachines', name=name)
#     jsonDict = jsonStr.copy()
#     jsonDict['kind'] = 'VirtualMachineImage'
#     jsonDict['metadata']['kind'] = 'VirtualMachineImage'
#     del jsonDict['metadata']['resourceVersion']
#     del jsonDict['spec']['lifecycle']
#     client.CustomObjectsApi().create_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachineimages', body=jsonDict)
#     client.CustomObjectsApi().delete_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachines', name=name, body=V1DeleteOptions())
#     logger.debug('convert VM to Image successful.')
#     
# def toVM(name):
#     jsonStr = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachineimages', name=name)
#     jsonDict = jsonStr.copy()
#     jsonDict['kind'] = 'VirtualMachine'
#     jsonDict['metadata']['kind'] = 'VirtualMachine'
#     del jsonDict['spec']['lifecycle']
#     del jsonDict['metadata']['resourceVersion']
#     client.CustomObjectsApi().create_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachines', body=jsonDict)
#     client.CustomObjectsApi().delete_namespaced_custom_object(
#         group=GROUP, version=VERSION, namespace='default', plural='virtualmachineimages', name=name, body=V1DeleteOptions())
#     logger.debug('convert Image to VM successful.')

def delete_image(name):
    file1 = '%s/%s.xml' % (DEFAULT_TEMPLATE_DIR, name)
    file2 = '%s/%s' % (DEFAULT_TEMPLATE_DIR, name)
    file3 = '%s/%s.path' % (DEFAULT_TEMPLATE_DIR, name)
    file4 = '%s/%s-nic-*' % (DEFAULT_TEMPLATE_DIR, name)
    file5 = '%s/%s-disk-*' % (DEFAULT_TEMPLATE_DIR, name)
    cmd = 'rm -rf %s %s %s %s %s' % (file1, file2, file3, file4, file5)
    try:
        runCmd(cmd)
    except:
        logger.error('Oops! ', exc_info=1)

def delete_vmdi(name, source):
    pool_info = get_pool_info_from_k8s(source)
    # result, data = rpcCallWithResult('kubesds-adm releaseDisk --vol %s' % name)
    sourcePool = pool_info['poolname']
    pool_path = get_pool_path(sourcePool)
    if pool_path is None:
        logger.debug('can not get pool path')
        exit(1)
    targetDir = '%s/%s' % (pool_path, name)
    cmd = 'rm -rf %s' % (targetDir)
    runCmd(cmd)
    
    write_result_to_server(name, 'delete', VMDI_KIND, VMDI_PLURAL, {'pool': pool_info['poolname']})

def updateOS(name, source, target):
    result, data = rpcCallWithResult('kubesds-adm prepareDisk --path %s' % source)
    result, data = rpcCallWithResult('kubesds-adm prepareDisk --path %s' % target)
    jsonDict = get_custom_object(GROUP, VERSION, VM_PLURAL, name)
    jsonString = json.dumps(jsonDict)
    if jsonString.find(source) >= 0 and os.path.exists(target):
        runCmd('cp %s %s' %(target, source))
    else:
        raise Exception('Wrong source or target.')
    jsonDict = deleteLifecycleInJson(jsonDict)
    vm_power_state = vm_state(name).get(name)
    body = addPowerStatusMessage(jsonDict, vm_power_state, 'The VM is %s' % vm_power_state)
    body = updateDescription(body)
    try:
        update_custom_object(GROUP, VERSION, VM_PLURAL, name, body)
    except ApiException, e:
        if e.reason == 'Conflict':
            logger.debug('**Other process updated %s, ignore this 409 error.' % name) 
        else:
            logger.error(e)
            raise e
#     pool = os.path.basename(os.path.dirname(os.path.dirname(source)))
#     vol = os.path.basename(source)
#     if vol and pool:
#         jsondict = client.CustomObjectsApi().get_namespaced_custom_object(
#             group=VMD_GROUP, version=VMD_VERSION, namespace='default', plural=VMD_PLURAL, name=vol)
#         vol_xml = get_volume_xml(pool, vol)
#         vol_path = get_volume_current_path(pool, vol)
#         vol_json = toKubeJson(xmlToJson(vol_xml))
#         vol_json = addSnapshots(vol_path, loads(vol_json))
#         jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
#         body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')
#         body = updateDescription(body)
#         try:
#             client.CustomObjectsApi().replace_namespaced_custom_object(
#                 group=VMD_GROUP, version=VMD_VERSION, namespace='default', plural=VMD_PLURAL, name=vol, body=body)
#         except ApiException, e:
#             if e.reason == 'Conflict':
#                 logger.debug('**Other process updated %s, ignore this 409 error.' % vol) 
#             else:
#                 logger.error(e)
#                 raise e    
#     else:
#         logger.error("Cannot get vm pool name or vm disk name: vmp(%s), vmd(%s)" % (pool, vol))
    
def create_disk_snapshot(vol, pool, snapshot):
    jsondict = get_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol)
    vol_path = get_volume_current_path(pool, vol)
    snapshots = get_volume_snapshots(vol_path)['snapshot']
    name_conflict = False
    for sn in snapshots:
        if sn.get('name') == snapshot:
            name_conflict = True
            break;
        else:
            continue
    if name_conflict:
        raise Exception('409, Conflict. Snapshot name %s already in use.' % snapshot)
    cmd = 'qemu-img snapshot -c %s %s' % (snapshot, vol_path)
    try:
        runCmd(cmd)
        vol_xml = get_volume_xml(pool, vol)
        vol_path = get_volume_current_path(pool, vol)
        vol_json = toKubeJson(xmlToJson(vol_xml))
        vol_json = addSnapshots(vol_path, loads(vol_json))
        jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
        body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')
        body = updateDescription(body)
        try:
            update_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol, body)
        except ApiException, e:
            if e.reason == 'Conflict':
                logger.debug('**Other process updated %s, ignore this 409 error.' % vol) 
            else:
                logger.error(e)
                raise e   
    except:
        logger.error('Oops! ', exc_info=1)
        info=sys.exc_info()
        report_failure(vol, jsondict, 'VirtletError', str(info[1]), VMD_GROUP, VMD_VERSION, VMD_PLURAL)

def delete_disk_snapshot(vol, pool, snapshot):
    jsondict = get_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol)
    vol_path = get_volume_current_path(pool, vol)
    cmd = 'qemu-img snapshot -d %s %s' % (snapshot, vol_path)
    try:
        runCmd(cmd)
        vol_xml = get_volume_xml(pool, vol)
        vol_path = get_volume_current_path(pool, vol)
        vol_json = toKubeJson(xmlToJson(vol_xml))
        vol_json = addSnapshots(vol_path, loads(vol_json))
        jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
        body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')
        body = updateDescription(body)
        try:
            update_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol, body)
        except ApiException, e:
            if e.reason == 'Conflict':
                logger.debug('**Other process updated %s, ignore this 409 error.' % vol) 
            else:
                logger.error(e)
                raise e   
    except:
        logger.error('Oops! ', exc_info=1)
        info=sys.exc_info()
        report_failure(vol, jsondict, 'VirtletError', str(info[1]), VMD_GROUP, VMD_VERSION, VMD_PLURAL)

def revert_disk_internal_snapshot(vol, pool, snapshot):
    jsondict = get_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol)
    vol_path = get_volume_current_path(pool, vol)
    cmd = 'qemu-img snapshot -a %s %s' % (snapshot, vol_path)
    try:
        runCmd(cmd)
        vol_xml = get_volume_xml(pool, vol)
        vol_path = get_volume_current_path(pool, vol)
        vol_json = toKubeJson(xmlToJson(vol_xml))
        vol_json = addSnapshots(vol_path, loads(vol_json))
        jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
        body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')
        body = updateDescription(body)
        try:
            update_custom_object(VMD_GROUP, VMD_VERSION, VMD_PLURAL, vol, body)
        except ApiException, e:
            if e.reason == 'Conflict':
                logger.debug('**Other process updated %s, ignore this 409 error.' % vol) 
            else:
                logger.error(e)
                raise e         
    except:
        logger.error('Oops! ', exc_info=1)
        info=sys.exc_info()
        report_failure(vol, jsondict, 'VirtletError', str(info[1]), VMD_GROUP, VMD_VERSION, VMD_PLURAL)
        
def revert_disk_external_snapshot(vol, pool, snapshot, leaves_str):
#     jsondict = client.CustomObjectsApi().get_namespaced_custom_object(
#         group=VMD_GROUP, version=VMD_VERSION, namespace='default', plural=VMD_PLURAL, name=vol)
    snapshot_path = get_volume_current_path(pool, snapshot)
    leaves = leaves_str.replace(' ', '').split(',')
    disks_to_delete = []
    for leaf in leaves:
        leaf_path = get_volume_current_path(pool, leaf)
        backing_chain = [leaf_path]
        backing_chain += DiskImageHelper.get_backing_files_tree(leaf_path)
        for backing_file in backing_chain:
            if backing_file == snapshot_path:
                break;
            else:
                disks_to_delete.append(backing_file)
    disks_to_delete = list(set(disks_to_delete))
    cmd1 = 'rm -f '
    for disk_to_delete in disks_to_delete:
        cmd1 = cmd1 + disk_to_delete + " "
    print(cmd1)
    runCmd(cmd1)

def _get_current(src_path):
    with open(src_path, "r") as f:
        config = json.load(f)
    return config.get('current')

def xmlToJson(xmlStr):
    return dumps(bf.data(fromstring(xmlStr)), sort_keys=True, indent=4)

def toKubeJson(json):
    return json.replace('@', '_').replace('$', 'text').replace(
            'interface', '_interface').replace('transient', '_transient').replace(
                    'nested-hv', 'nested_hv').replace('suspend-to-mem', 'suspend_to_mem').replace('suspend-to-disk', 'suspend_to_disk')

def _solve_conflict_in_create_vmdi(name, group, version, plural, params):
    for i in range(1, 6):
        try:
            jsondict = get_custom_object(group, version, plural, name)
            vol_json = {'volume': get_vol_info_by_qemu(params.get('current'))}
            vol_json = add_spec_in_volume(vol_json, 'current', params.get('current'))
            vol_json = add_spec_in_volume(vol_json, 'disk', name)
            vol_json = add_spec_in_volume(vol_json, 'pool', params.get('pool'))
            vol_json = add_spec_in_volume(vol_json, 'poolname', params.get('poolname'))
            jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
            body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')  
            update_custom_object(group, version, plural, name, body)
            return
        except Exception, e:
            if i == 5:
                raise e
                    
def write_result_to_server(name, op, kind, plural, params):
    if op == 'create':
        logger.debug('Create %s %s, report to virtlet' % (kind, name))
        jsondict = {'spec': {'volume': {}, 'nodeName': HOSTNAME, 'status': {}},
                    'kind': kind, 'metadata': {'labels': {'host': HOSTNAME}, 'name': name},
                    'apiVersion': '%s/%s' % (GROUP, VERSION)}
        
#             with open(get_pool_path(params.get('pool')) + '/' + name + '/config.json', "r") as f:
#                 config = json.load(f)
        vol_json = {'volume': get_vol_info_by_qemu(params.get('current'))}
        vol_json = add_spec_in_volume(vol_json, 'current', params.get('current'))
        vol_json = add_spec_in_volume(vol_json, 'disk', name)
        vol_json = add_spec_in_volume(vol_json, 'pool', params.get('pool'))
        vol_json = add_spec_in_volume(vol_json, 'poolname', params.get('poolname'))
        jsondict = updateJsonRemoveLifecycle(jsondict, vol_json)
        body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')    
        try:
            create_custom_object(GROUP, VERSION, plural, body)
        except ApiException, e:
            if e.reason == 'Conflict':
                _solve_conflict_in_create_vmdi(name, GROUP, VERSION, plural, params)
            else:
                logger.error(e)
                raise e  
    elif op == 'delete':
        try:
            refresh_pool(params.get('pool'))
            print name
            jsondict = get_custom_object(GROUP, VERSION, plural, name)
            #             vol_xml = get_volume_xml(pool, name)
            #             vol_json = toKubeJson(xmlToJson(vol_xml))
            jsondict = updateJsonRemoveLifecycle(jsondict, {})
            body = addPowerStatusMessage(jsondict, 'Ready', 'The resource is ready.')
            update_custom_object(GROUP, VERSION, plural, name, body)
        except ApiException, e:
            if e.reason == 'Not Found':
                logger.debug('**%s %s already deleted.' % (kind, name))
            else:
                logger.error(e)
                raise e   
        except:
            logger.error('Oops! ', exc_info=1)
        try:
            logger.debug('deleteVMBackupdebug %s' % name)
            delete_custom_object(GROUP, VERSION, plural, name)
        except ApiException, e:
            if e.reason == 'Not Found':
                logger.debug('**%s %s already deleted.' % (kind, name))
            else:
                logger.error(e)
                raise e               

def main():
    help_msg = 'Usage: %s <convert_vm_to_image|convert_image_to_vm|convert_vmd_to_vmdi|convert_vmdi_to_vmd|create_disk_snapshot|delete_disk_snapshot|revert_disk_internal_snapshot|revert_disk_external_snapshot|merge_disk_snapshot|create_disk_from_vmdi|delete_image|create_vmdi|delete_vmdi|update-os|--help>' % sys.argv[0]
    if len(sys.argv) < 2 or sys.argv[1] == '--help':
        print (help_msg)
        sys.exit(1)
    print sys.argv
    if len(sys.argv)%2 != 0:
        print ("wrong parameter number")
        sys.exit(1)
 
    params = {}
    for i in range(2, len(sys.argv) - 1):
        params[sys.argv[i]] = sys.argv[i+1]
        i = i+2
    
#     if sys.argv[1] == 'create_vm_image_from_vm':
#         create_vm_image_from_vm(params['--name'], params['--domain'], params['--targetPool'])
#     elif sys.argv[1] == 'convert_image_to_vm':
#         convert_image_to_vm(params['--name'])
    if sys.argv[1] == 'create_vmdi_from_disk':
        create_vmdi_from_disk(params['--name'], params['--sourceVolume'], params['--sourcePool'], params['--targetPool'])
#     elif sys.argv[1] == 'convert_vmdi_to_vmd':
#         convert_vmdi_to_vmd(params['--name'], params['--sourcePool'], params['--targetPool'])    
#     elif sys.argv[1] == 'create_disk_from_vmdi':
#         create_disk_from_vmdi(params['--name'], params['--targetPool'], params['--source'])
#     elif sys.argv[1] == 'create_disk_snapshot':
#         create_disk_snapshot(params['--name'], params['--pool'], params['--snapshotname'])
#     elif sys.argv[1] == 'delete_disk_snapshot':
#         delete_disk_snapshot(params['--name'], params['--pool'], params['--snapshotname'])
#     elif sys.argv[1] == 'revert_disk_internal_snapshot':
#         revert_disk_internal_snapshot(params['--name'], params['--pool'], params['--snapshotname'])
#     elif sys.argv[1] == 'revert_disk_external_snapshot':
#         revert_disk_external_snapshot(params['--name'], params['--pool'], params['--snapshotname'], params['--leaves'])
#     elif sys.argv[1] == 'delete_image':
#         delete_image(params['--name'])
    elif sys.argv[1] == 'create_vmdi':
        create_vmdi(params['--name'], params['--targetPool'])
    elif sys.argv[1] == 'delete_vmdi':
        delete_vmdi(params['--name'], params['--sourcePool'])
    elif sys.argv[1] == 'update-os':
        updateOS(params['--domain'], params['--source'], params['--target'])
    else:
        print ('invalid argument!')
        print (help_msg)


'''
Run back-end command in subprocess.
'''
def runCmd(cmd):
    logger.debug(cmd)
    std_err = None
    if not cmd:
        return
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        std_out = p.stdout.readlines()
        std_err = p.stderr.readlines()
        if std_out:
#             msg = ''
#             for index,line in enumerate(std_out):
#                 if not str.strip(line):
#                     continue
#                 if index == len(std_out) - 1:
#                     msg = msg + str.strip(line) + '. '
#                 else:
#                     msg = msg + str.strip(line) + ', '
#             logger.debug(str.strip(msg))
            logger.debug(std_out)
        if std_err:
#             msg = ''
#             for index, line in enumerate(std_err):
#                 if not str.strip(line):
#                     continue
#                 if index == len(std_err) - 1:
#                     msg = msg + str.strip(line) + '. ' + '***More details in %s***' % LOG
#                 else:
#                     msg = msg + str.strip(line) + ', '
            logger.error(std_err)
#             raise ExecuteException('VirtctlError', str.strip(msg))
            raise ExecuteException('VmmError', std_err)
#         return (str.strip(std_out[0]) if std_out else '', str.strip(std_err[0]) if std_err else '')
        return
    finally:
        p.stdout.close()
        p.stderr.close()

def runCmdWithResult(cmd):
    if not cmd:
        return
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        std_out = p.stdout.readlines()
        std_err = p.stderr.readlines()
        if std_out:
            msg = ''
            for index, line in enumerate(std_out):
                if not str.strip(line):
                    continue
                msg = msg + str.strip(line)
            msg = str.strip(msg)
            logger.debug(msg)
            try:
                result = loads(msg)
                if isinstance(result, dict) and 'result' in result.keys():
                    if result['result']['code'] != 0:
                        if std_err:
                            error_msg = ''
                            for index, line in enumerate(std_err):
                                if not str.strip(line):
                                    continue
                                error_msg = error_msg + str.strip(line)
                            error_msg = str.strip(error_msg).replace('"', "'")
                            result['result']['msg'] = '%s. cstor error output: %s' % (
                            result['result']['msg'], error_msg)
                return result
            except Exception:
                logger.debug(cmd)
                logger.debug(traceback.format_exc())
                error_msg = ''
                for index, line in enumerate(std_err):
                    if not str.strip(line):
                        continue
                    error_msg = error_msg + str.strip(line)
                error_msg = str.strip(error_msg)
                raise ExecuteException('RunCmdError',
                                       'can not parse cstor-cli output to json----' + msg + '. ' + error_msg)
        if std_err:
            msg = ''
            for index, line in enumerate(std_err):
                msg = msg + line + ', '
            logger.debug(cmd)
            logger.debug(msg)
            logger.debug(traceback.format_exc())
            if msg.strip() != '':
                raise ExecuteException('RunCmdError', msg)
    finally:
        p.stdout.close()
        p.stderr.close()

def get_pool_info_from_k8s(pool):
    result = None
    for i in range(30):
        try:
            result = runCmdWithResult('kubectl get vmp --kubeconfig=/root/.kube/config -o json %s' % pool)
            break
        except Exception:
            logger.debug(traceback.format_exc())
            if i == 29:
                raise ExecuteException('', 'can not get pool info from k8s')

    if result == None:
        raise ExecuteException('', 'can not get pool info from k8s')
    if 'spec'in result.keys() and isinstance(result['spec'], dict) and 'pool' in result['spec'].keys():
        return result['spec']['pool']
    raise ExecuteException('', 'can not get pool info from k8s')

def get_vol_info_from_k8s(vol):
    if not vol:
        raise ExecuteException('', 'missing parameter: no disk name.')
    result = None
    for i in range(30):
        try:
            result = runCmdWithResult('kubectl get vmd --kubeconfig=/root/.kube/config -o json %s' % vol)
            break
        except Exception:
            logger.debug(traceback.format_exc())
            if i == 29:
                raise ExecuteException('', 'can not get pool info from k8s')
    if result == None:
        raise ExecuteException('', 'can not get pool info from k8s')
    if 'spec'in result.keys() and isinstance(result['spec'], dict) and 'volume' in result['spec'].keys():
        return result['spec']['volume']
    raise ExecuteException('', 'can not get vol info from k8s')

# def run(cmd):
#     try:
#         result = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
#         logger.debug(result)
#         print result
#     except Exception:
#         traceback.format_exc()
#         print(sys.exc_info())
#         raise ExecuteException('vmmError', sys.exc_info()[1])


if __name__ == '__main__':
    config.load_kube_config(config_file="/root/.kube/config")
    main()
    pass
