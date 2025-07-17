# alertissimo/core/brokers/fink.py
from .base import Broker

class FinkBroker(Broker):
    def __init__(self):
        super().__init__(
            name="Fink",
            base_url="https://api.fink-portal.org/api/v1"
        )

    def get_object_data(self, object_id: str):
        return self.request(
            endpoint="objects",
            params={"objectId": object_id}
        )

    def is_available(self) -> bool:
        # Fink REST api is publicly available without credentials
        return True


#    def is_available(self) -> bool:
#        return Path.home().joinpath(".fink-client", "token.yaml").exists()
