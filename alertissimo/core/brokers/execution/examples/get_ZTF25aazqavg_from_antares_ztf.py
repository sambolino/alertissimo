from alertissimo.core.brokers.execution import RegistryEndpointExecutor

result = RegistryEndpointExecutor().call("antares", "ztf", "get_by_ztf_object_id", ztf_object_id="ZTF25aazqavg")
print(result.payload)
