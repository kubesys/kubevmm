/**
 * Copyright (2019, ) Institute of Software, Chinese Academy of Sciences
 */
package com.github.kube.controller.watchers;

import java.util.HashMap;
import java.util.Map;
import java.util.logging.Level;

import com.github.kube.controller.KubevirtConstants;
import com.github.kube.controller.KubevirtWatcher;
import com.github.kubesys.kubernetes.ExtendedKubernetesClient;
import com.github.kubesys.kubernetes.api.model.VirtualMachineNetwork;

import io.fabric8.kubernetes.api.model.Quantity;
import io.fabric8.kubernetes.api.model.ResourceRequirements;
import io.fabric8.kubernetes.client.KubernetesClientException;
import io.fabric8.kubernetes.client.Watcher;

/**
 * @author wuheng@otcaix.iscas.ac.cn
 * 
 * @version 1.0.0
 * @since Wed Aug 29 17:26:22 CST 2019
 * 
 * convert VirtualMachineNetwork to Pod. 
 **/
public class VirtualMachineNetworkWatcher extends KubevirtWatcher implements Watcher<VirtualMachineNetwork> {

	/**
	 * @param client        client
	 */
	public VirtualMachineNetworkWatcher(ExtendedKubernetesClient client) {
		super(client);
	}


	public void eventReceived(Action action, VirtualMachineNetwork network) {
		eventReceived(action, network.getKind(), network.getMetadata(), network.getSpec());
	}

	@Override
	public ResourceRequirements getResourceDemands(Object spec) {
		ResourceRequirements resources = new ResourceRequirements();
		Map<String, Quantity> requests = new HashMap<String, Quantity>();
		requests.put(KubevirtConstants.CPU_RESOURCE, new Quantity("100m"));
		requests.put(KubevirtConstants.RAM_RESOURCE, new Quantity("64Mi"));
		resources.setRequests(requests);
		return resources;
	}


	@Override
	public void onClose(KubernetesClientException cause) {
		m_logger.log(Level.SEVERE, cause.toString());
		client.watchVirtualMachineNetworks(this);
	}

}
