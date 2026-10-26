#!/usr/bin/env python3
"""Import one enhanced ROS node and report generated message field metadata."""

from __future__ import print_function

import argparse
import importlib
import json
import platform
import socket


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("node", choices=("sentinel", "scout"))
    arguments = parser.parse_args()

    from drone_enhanced_interfaces.msg import (
        HazardAlert,
        HazardDecision,
        HazardVerdict,
    )

    node_module = importlib.import_module(
        "drone_enhanced_nodes.{}_node".format(arguments.node)
    )
    result = {
        "status": "PASS",
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "node": arguments.node,
        "node_module": node_module.__name__,
        "message_fields": {
            "HazardAlert": HazardAlert.get_fields_and_field_types(),
            "HazardVerdict": HazardVerdict.get_fields_and_field_types(),
            "HazardDecision": HazardDecision.get_fields_and_field_types(),
        },
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
