/**
 * Copyright (2019, ) Institute of Software, Chinese Academy of Sciences
 */
package com.github.kube.controller.watchers;

import java.util.HashMap;
import java.util.Map;

import com.github.kube.controller.KubevirtConstants;
import com.github.kube.controller.KubevirtWatcher;
import com.github.kubesys.kubernetes.ExtendedKubernetesClient;
import com.github.kubesys.kubernetes.api.model.VirtualMachinePool;

import io.fabric8.kubernetes.api.model.Quantity;
import io.fabric8.kubernetes.api.model.ResourceRequirements;
import io.fabric8.kubernetes.client.Watcher;

/**
 * @author wuheng@otcaix.iscas.ac.cn
 * 
 * @version 1.0.0
 * @since Wed Aug 29 17:26:22 CST 2019
 * 
 * convert VirtualMachinePool to Pod. 
 **/
public class VirtualMachinePoolWatcher extends KubevirtWatcher implements Watcher<VirtualMachinePool> {


	/**
	 * @param client             client
	 */
	public VirtualMachinePoolWatcher(ExtendedKubernetesClient client) {
		super(client);
	}

	public void eventReceived(Action action, VirtualMachinePool pool) {
		eventReceived(action, pool.getKind(), pool.getMetadata(), pool.getSpec());
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

}
