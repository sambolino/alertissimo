from alertissimo.core.brokers.execution import RegistryEndpointExecutor

result = RegistryEndpointExecutor().call("lasair", "ztf", "object", objectId="ZTF25aazqavg")
print(result.payload)
