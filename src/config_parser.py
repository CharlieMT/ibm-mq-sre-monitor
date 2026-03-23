import json
import os
import glob
import re

def parse_size(size_str):
    """Convert size string like '20MB' to bytes."""
    if not size_str:
        return 20 * 1024 * 1024  # Default 20MB
    
    # Match pattern like 20MB, 50MB, 1GB, etc.
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMG]?B)$', size_str.upper())
    if not match:
        return 20 * 1024 * 1024  # Default 20MB
    
    size, unit = match.groups()
    size = float(size)
    
    multipliers = {
        'B': 1,
        'KB': 1024,
        'MB': 1024 * 1024,
        'GB': 1024 * 1024 * 1024
    }
    
    return int(size * multipliers.get(unit, 1))

def parse_interval(interval_str):
    """Convert interval string like '5s', '1m', '1h' to seconds."""
    if not interval_str:
        return 5  # Default 5 seconds
    
    # Match pattern like 5s, 30s, 1m, 2m, 1h, etc.
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([smh]?)$', interval_str.lower())
    if not match:
        return 5  # Default 5 seconds
    
    size, unit = match.groups()
    size = float(size)
    
    multipliers = {
        '': 1,      # seconds if no unit
        's': 1,     # seconds
        'm': 60,    # minutes
        'h': 3600   # hours
    }
    
    return int(size * multipliers.get(unit, 1))

def load_app_config(config_file="app_config.conf"):
    """Load application configuration from config file."""
    config = {}
    current_section = None
    
    if not os.path.exists(config_file):
        print(f"Warning: Configuration file '{config_file}' not found. Using defaults.")
        return config
    
    try:
        with open(config_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Check for section header
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1].strip()
                    continue
                
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Store with section prefix if in a section
                    if current_section:
                        config[f"{current_section}.{key}"] = value
                    else:
                        config[key] = value
    except Exception as e:
        print(f"Warning: Error reading config file: {e}")
    
    # Set defaults for logging configuration
    config.setdefault('log_dir', 'mq_logs')
    config.setdefault('log_file', 'mq_monitor.log')
    config.setdefault('log_level', 'INFO')
    config.setdefault('log_max_size', '20MB')
    config.setdefault('log_backup_count', '5')
    config.setdefault('tick_rate', '5s')
    
    # Set defaults for alerts configuration
    config.setdefault('Alerts.global_alerts_enable', 'true')
    config.setdefault('Alerts.api_url', 'https://alerts-api.nazwaklienta.test/api/v1/alerts')
    config.setdefault('Alerts.api_key', 'your_key_here')
    
    # Parse size string to bytes
    config['log_max_size'] = parse_size(config.get('log_max_size', '20MB'))
    
    # Parse backup count to int
    try:
        config['log_backup_count'] = int(config.get('log_backup_count', '5'))
    except ValueError:
        config['log_backup_count'] = 5
    
    # Parse tick rate to seconds
    config['tick_rate'] = parse_interval(config.get('tick_rate', '5s'))
    
    # Parse boolean for global_alerts_enable
    try:
        alerts_enable_str = config.get('Alerts.global_alerts_enable', 'true').lower()
        config['Alerts.global_alerts_enable'] = alerts_enable_str in ('true', 'yes', '1', 'on')
    except (ValueError, AttributeError):
        config['Alerts.global_alerts_enable'] = True
    
    return config

def load_configurations(directories):
    """Load configurations from multiple directories."""
    configs = []
    
    if isinstance(directories, str):
        directories = [directories]
    
    for directory in directories:
        if not directory:
            continue
            
        if not os.path.exists(directory):
            print(f"Warning: Configuration directory '{directory}' does not exist.")
            continue
        
        json_files = glob.glob(os.path.join(directory, "*.json"))
        
        for filepath in json_files:
            try:
                with open(filepath, 'r') as f:
                    config = json.load(f)
                    # Ensure interval key exists with default of 60 seconds
                    if 'interval' not in config:
                        config['interval'] = 60
                    configs.append(config)
                    print(f"Loaded configuration from {os.path.basename(filepath)}")
            except json.JSONDecodeError as e:
                print(f"Warning: Invalid JSON in {os.path.basename(filepath)}: {e}. Skipping.")
            except Exception as e:
                print(f"Warning: Error reading {os.path.basename(filepath)}: {e}. Skipping.")
    
    return configs

def get_config_value(config, key, default=None):
    return config.get(key, default)
