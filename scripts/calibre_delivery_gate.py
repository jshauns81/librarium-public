"""Synthetic-only Calibre owner/cache acceptance, executed by calibre-debug."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def main():
    spec = spec_from_file_location(
        "delivery_owner", Path(__file__).with_name("calibre_delivery_owner.py")
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    module.prove()


if __name__ == "__main__":
    main()
