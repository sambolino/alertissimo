Lasair and Alerce don't need installation (for now), we are pulling data via rest api
Install Fink and Antares (see requirements.txt)

Copy .env.example to .env on your system

See how to get Lasair token below - then copy it to .env
https://lasair.readthedocs.io/en/main/core_functions/rest-api.html

To enable Fink-based confirmation and enrichments, you must register with your credentials:
pip install fink-client --upgrade

fink_client_register \
    -username <USERNAME> \
    -group_id <GROUP_ID> \
    -mytopics <topic1 topic2 etc> \
    -servers kafka-ztf.fink-broker.org:24499 \
    -maxtimeout 10 \
    --verbose

This stores your secure Kafka token at:

~/.fink-client/token.yaml
