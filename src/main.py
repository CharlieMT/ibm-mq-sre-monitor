import time
import logging
import logging.handlers
import os
import gzip
import shutil
from config_parser import load_app_config, load_configurations, parse_interval
from mq_connector import MQConnector
from alert_manager import AlertManager

def namer(name):
    """Custom namer to add .gz extension to rotated log files."""
    return name + ".gz"

def rotator(source, dest):
    """Custom rotator to compress log files with gzip."""
    with open(source, 'rb') as f_in:
        with gzip.open(dest, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)

def setup_logger(app_config):
    """Set up logging with rotation and compression."""
    # Create log directory if it doesn't exist
    log_dir = app_config.get('log_dir', 'mq_logs')
    os.makedirs(log_dir, exist_ok=True)
    
    # Construct full log path
    log_file = app_config.get('log_file', 'mq_monitor.log')
    full_log_path = os.path.join(log_dir, log_file)
    
    # Configure root logger
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    
    # Remove any existing handlers
    logger.handlers.clear()
    
    # Create rotating file handler with compression
    max_bytes = app_config.get('log_max_size', 20 * 1024 * 1024)
    backup_count = app_config.get('log_backup_count', 5)
    
    file_handler = logging.handlers.RotatingFileHandler(
        full_log_path,
        maxBytes=max_bytes,
        backupCount=backup_count
    )
    
    # Attach custom rotator and namer for compression
    file_handler.rotator = rotator
    file_handler.namer = namer
    
    # Set log level from config
    log_level_str = app_config.get('log_level', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    file_handler.setLevel(log_level)
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    logging.info(f"Logging initialized. Log file: {full_log_path}")
    logging.info(f"Log level: {log_level_str}, Max size: {max_bytes} bytes, Backups: {backup_count}")

def evaluate_rule(value, operator, threshold):
    """
    Evaluate a rule dynamically with type casting.
    
    Args:
        value: The value to evaluate (string from MQ)
        operator: The operator to use (">", "<", "==", "!=", ">=", "<=")
        threshold: The threshold value to compare against
    
    Returns:
        Boolean result of the evaluation
    """
    try:
        # Determine if threshold is numeric or string
        if isinstance(threshold, (int, float)) or (isinstance(threshold, str) and threshold.replace('.', '', 1).isdigit()):
            # Try to convert value to float for numeric comparison
            try:
                value_num = float(value)
                threshold_num = float(threshold)
                
                # Perform numeric comparison
                if operator == ">":
                    return value_num > threshold_num
                elif operator == "<":
                    return value_num < threshold_num
                elif operator == "==":
                    return value_num == threshold_num
                elif operator == "!=":
                    return value_num != threshold_num
                elif operator == ">=":
                    return value_num >= threshold_num
                elif operator == "<=":
                    return value_num <= threshold_num
                else:
                    logging.error(f"Unsupported operator for numeric comparison: {operator}")
                    return False
            except ValueError:
                # If conversion fails, fall back to string comparison
                logging.warning(f"Could not convert value '{value}' or threshold '{threshold}' to numeric. Falling back to string comparison.")
        
        # String comparison
        if operator == "==":
            return str(value) == str(threshold)
        elif operator == "!=":
            return str(value) != str(threshold)
        elif operator == ">":
            return str(value) > str(threshold)
        elif operator == "<":
            return str(value) < str(threshold)
        elif operator == ">=":
            return str(value) >= str(threshold)
        elif operator == "<=":
            return str(value) <= str(threshold)
        else:
            logging.error(f"Unsupported operator: {operator}")
            return False
            
    except Exception as e:
        logging.error(f"Error evaluating rule: value={value}, operator={operator}, threshold={threshold}. Error: {e}")
        return False

def main():
    # Load application configuration
    app_config = load_app_config()
    
    # Set up logging
    setup_logger(app_config)
    
    # Load check configurations from multiple directories
    queues_dir = app_config.get('queues_dir', 'mq_checks_config/queues')
    channels_dir = app_config.get('channels_dir', 'mq_checks_config/channels')
    
    configs = load_configurations([queues_dir, channels_dir])
    
    if not configs:
        logging.error("No valid configurations found. Exiting.")
        return
    
    logging.info(f"Loaded {len(configs)} configuration(s). Starting monitoring loop...")
    
    # Initialize next_run time for each configuration
    for config in configs:
        config['next_run'] = 0  # 0 means run immediately on first iteration

    # Initialize AlertManager conditionally based on configuration
    alert_manager = None
    global_alerts_enable = app_config.get('Alerts.global_alerts_enable', True)
    api_url = app_config.get('Alerts.api_url', 'https://alerts-api.nazwaklienta.test/api/v1/alerts')
    api_key = app_config.get('Alerts.api_key', 'your_key_here')
    service_name = app_config.get('Alerts.service_name', 'IBM_MQ_MONITOR')
    http_backend = app_config.get('Alerts.http_backend', 'urllib')
    
    if global_alerts_enable:
        logging.info(f"Starting Alert Manager with service name '{service_name}' and HTTP backend '{http_backend}'...")
        alert_manager = AlertManager(api_url, api_key, service_name, http_backend)
    else:
        logging.info("Alert Manager is disabled via configuration (global_alerts_enable = false)")
    
    try:
        while True:
            current_time = time.time()
            
            for config in configs:
                # Check if it's time to run this configuration
                if current_time < config['next_run']:
                    continue
                
                queue_manager = config.get('queue_manager')
                object_name = config.get('object_name')
                check_type = config.get('check_type')
                operator = config.get('operator', '==')
                threshold = config.get('threshold')
                alert_severity = config.get('alert_severity', 'major')
                enable_check = config.get('enable_check', True)
                enable_alert = config.get('enable_alert', True)
                
                if not enable_check:
                    # Still schedule next run even if disabled
                    config['next_run'] = current_time + config.get('interval', 60)
                    continue
                
                mq_connector = MQConnector(queue_manager)
                
                # Determine object type from check_type or directory (QUEUE or CHANNEL)
                # For backward compatibility, infer from check_type
                if check_type == 'CURDEPTH':
                    obj_type = 'QUEUE'
                elif check_type == 'STATUS':
                    obj_type = 'CHANNEL'
                else:
                    # Try to infer from configuration directory or use QUEUE as default
                    obj_type = config.get('object_type', 'QUEUE')
                
                # Get the attribute value using universal method
                value = mq_connector.get_mq_attribute(obj_type, object_name, check_type)
                
                if value is None:
                    logging.error(f"[{queue_manager}] Attribute '{check_type}' not found for {obj_type} '{object_name}'. Is the attribute valid or MQ CLI available?")
                    if alert_manager and enable_alert:
                        # Trigger a 'critical' CLI_ERROR alert as specified in requirements
                        alert_manager.process_state(queue_manager, object_name, check_type, True, 
                                                   f"CLI/Connection Error - cannot read {check_type} for {obj_type}", 
                                                   "N/A", enable_alert, severity='critical')
                else:
                    # Evaluate the rule dynamically
                    is_failing = evaluate_rule(value, operator, threshold)
                    
                    if is_failing:
                        logging.error(f"{obj_type} {object_name} {check_type} is {value}! (rule: {check_type} {operator} {threshold})")
                    else:
                        logging.info(f"[{queue_manager}] {obj_type} '{object_name}' {check_type}: {value}")
                
                    # Always send current state to Alert Manager
                    if alert_manager and enable_alert:
                        msg = f"{obj_type} {check_type} rule violation. Current: {value}, Rule: {check_type} {operator} {threshold}"
                        alert_manager.process_state(queue_manager, object_name, check_type, is_failing, 
                                                   msg, value, enable_alert, severity=alert_severity)
                
                # Schedule next run for this configuration
                config['next_run'] = current_time + config.get('interval', 60)
            
            # Sleep for tick rate before next iteration
            tick_rate = app_config.get('tick_rate', 5)
            time.sleep(tick_rate)
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user. Shutting down gracefully...")

if __name__ == "__main__":
    main()
