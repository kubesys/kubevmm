'''
Copyright (2019, ) Institute of Software, Chinese Academy of Sciences

@author: wuyuewen@otcaix.iscas.ac.cn
@author: wuheng@otcaix.iscas.ac.cn

'''
 
import os, sys, ConfigParser, traceback, time, socket
from multiprocessing import Process

'''
Import third party libs
'''
from kubernetes import config

'''
Import local libs
'''
# sys.path.append('%s/utils' % (os.path.dirname(os.path.realpath(__file__))))
from utils.utils import CDaemon, runCmd, singleton
from utils import logger
from libvirt_event_handler import main as libvirt_event_handler
from libvirt_event_handler_for_4_0 import main as libvirt_event_handler_4_0

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

TOKEN = config_raw.get('Kubernetes', 'token_file')
HOSTNAME = socket.gethostname()
logger = logger.set_logger(os.path.basename(__file__), '/var/log/virtlet.log')

class ClientDaemon(CDaemon):
    def __init__(self, name, save_path, stdin=os.devnull, stdout=os.devnull, stderr=os.devnull, home_dir='.', umask=022, verbose=1):
        CDaemon.__init__(self, save_path, stdin, stdout, stderr, home_dir, umask, verbose)
        self.name = name
 
    @singleton('/var/run/libvirt_watcher_daemon.pid')
    def run(self, output_fn, **kwargs):
        logger.debug("---------------------------------------------------------------------------------")
        logger.debug("--------------------Welcome to Libvirt Watcher Daemon.---------------------------")
        logger.debug("------Copyright (2019, ) Institute of Software, Chinese Academy of Sciences------")
        logger.debug("---------author: wuyuewen@otcaix.iscas.ac.cn,liuhe18@otcaix.iscas.ac.cn----------")
        logger.debug("--------------------------------wuheng@otcaix.iscas.ac.cn------------------------")
        logger.debug("---------------------------------------------------------------------------------")
        
        config.load_kube_config(config_file=TOKEN)
        try:
            thread_1 = Process(target=get_libvirt_event_handler())
            thread_1.daemon = True
            thread_1.name = 'libvirt_event_handler'
            thread_1.start()
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                return
            thread_1.join()
        except:
            logger.error('Oops! ', exc_info=1)
            
def is_kubernetes_master():
    if runCmd('kubectl get node %s | grep master' % HOSTNAME):
        return True
    else:
        return False
    
def get_libvirt_event_handler():
    retv = runCmd('virsh --version')
    if retv.strip().startswith("4.0"):
        return libvirt_event_handler_4_0
    else:
        return libvirt_event_handler
            
def daemonize():
    help_msg = 'Usage: python %s <start|stop|restart|status>' % sys.argv[0]
    if len(sys.argv) != 2:
        print help_msg
        sys.exit(1)
    p_name = 'virtlet'
    pid_fn = '/var/run/libvirt_watcher_daemon.pid'
    log_fn = '/var/log/libvirt_watcher.log'
    err_fn = '/var/log/libvirt_watcher.log'
    cD = ClientDaemon(p_name, pid_fn, stderr=err_fn, verbose=1)
 
    if sys.argv[1] == 'start':
        cD.start(log_fn)
    elif sys.argv[1] == 'stop':
        cD.stop()
    elif sys.argv[1] == 'restart':
        cD.restart(log_fn)
    elif sys.argv[1] == 'status':
        alive = cD.is_running()
        if alive:
            print 'process [%s] is running ......' % cD.get_pid()
        else:
            print 'daemon process [%s] stopped' %cD.name
    else:
        print 'invalid argument!'
        print help_msg    
 
 
if __name__ == '__main__':
    daemonize()


