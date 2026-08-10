from alertissimo.core.brokers.execution import RegistryEndpointExecutor

result = RegistryEndpointExecutor().call("fink", "ztf", "objects", objectId="ZTF19acmdpyr")
print(result.payload)
