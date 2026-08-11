# Lasair payload fixtures

The JSON files in this directory are saved examples used for authoritative
payload-path coverage. The ZTF fixtures retain the exact `ZTF20acpwljl` example;
the LSST fixtures are provisional until production LSST responses are available.

The cone API contract documents `requestType=count` as returning the number of
objects within the cone. Its exact serialized response shape has not yet been
captured from an actual response, server source, or an official example, so
count responses are not part of authoritative payload coverage.
