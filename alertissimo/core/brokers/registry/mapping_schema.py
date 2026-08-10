"""Compatibility wrapper; use :mod:`alertissimo.data_layer.runtime.mapping_schema`."""
from alertissimo.data_layer.runtime.mapping_schema import *  # noqa: F401,F403

if __name__ == "__main__":
    from alertissimo.data_layer.runtime.mapping_schema import main
    raise SystemExit(main())
