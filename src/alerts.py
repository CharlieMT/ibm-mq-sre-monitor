
import json
import os

from src.config_parser import load_configurations, get_config_value

class Alerts:
    def __init__(self):
        # Load all configurations from the MQ_Check directory
        all_configs = load_configurations()
        # Assuming alerts configuration is part of one of these configs
        # You might need to adjust this logic to specifically find the alerts config
        self.alerts_config = {}
        for config in all_configs:
            if "alerts_config" in config:
                self.alerts_config = config.get("alerts_config", {})
                break # Assuming the first found alerts_config is sufficient

    # Removed _load_alerts_config as configurations are loaded via load_configurations now



    def check_threshold(self, metric_name, current_value):
        thresholds = self.alerts_config.get(metric_name, {})
        warning_threshold = thresholds.get("warning")
        critical_threshold = thresholds.get("critical")

        if critical_threshold is not None and current_value >= critical_threshold:
            return f"CRITICAL: {metric_name} is at {current_value}, exceeding critical threshold of {critical_threshold}"
        elif warning_threshold is not None and current_value >= warning_threshold:
            return f"WARNING: {metric_name} is at {current_value}, exceeding warning threshold of {warning_threshold}"
        return None

    def generate_alert_message(self, component_type, component_name, metric, value, threshold_type, threshold_value):
        return f"{threshold_type.upper()}: {component_type} {component_name} - {metric} is {value}, threshold {threshold_type} is {threshold_value}"
