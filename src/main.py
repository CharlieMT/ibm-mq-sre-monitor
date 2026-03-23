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
    
    if global_alerts_enable:
        logging.info("Starting Alert Manager and syncing state...")
        alert_manager = AlertManager(api_url, api_key)
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
                max_threshold = config.get('max_threshold')
                enable_check = config.get('enable_check', True)
                enable_alert = config.get('enable_alert', True)
                
                if not enable_check:
                    # Still schedule next run even if disabled
                    config['next_run'] = current_time + config.get('interval', 60)
                    continue
                
                mq_connector = MQConnector(queue_manager)
                
                if check_type == 'CURDEPTH':
                    queue_depth = mq_connector.get_queue_depth(object_name)
                    
                    if queue_depth is None:
                        logging.error(f"[{queue_manager}] Could not retrieve depth for queue '{object_name}'. Is IBM MQ CLI available?")
                        if alert_manager and enable_alert:
                            alert_manager.process_state(queue_manager, object_name, "CURDEPTH", True, "CLI/Connection Error - cannot read queue depth", "N/A", enable_alert)
                    else:
                        is_failing = queue_depth > max_threshold
                        if is_failing:
                            logging.error(f"Queue {object_name} depth is {queue_depth}! (threshold: {max_threshold})")
                        else:
                            logging.info(f"[{queue_manager}] Queue '{object_name}' depth: {queue_depth}")
                
                        # Zawsze wysyłamy aktualny stan do Alert Managera (on sam decyduje, co z tym zrobić)
                        if alert_manager and enable_alert:
                            msg = f"Queue depth limit exceeded. Current: {queue_depth}, Threshold: {max_threshold}"
                            alert_manager.process_state(queue_manager, object_name, "CURDEPTH", is_failing, msg, queue_depth, enable_alert)
                
                elif check_type == 'STATUS':
                    channel_status = mq_connector.get_channel_status(object_name)
                    
                    if channel_status is None:
                        logging.error(f"[{queue_manager}] Could not retrieve status for channel '{object_name}'. Is IBM MQ CLI available?")
                        if alert_manager and enable_alert:
                            alert_manager.process_state(queue_manager, object_name, "STATUS", True, "CLI/Connection Error - cannot read channel status", "N/A", enable_alert)
                    else:
                        is_failing = channel_status != max_threshold
                        if is_failing:
                            logging.error(f"Channel {object_name} is currently {channel_status}! (expected: {max_threshold})")
                        else:
                            logging.info(f"[{queue_manager}] Channel '{object_name}' status: {channel_status}")
                
                        # Zawsze wysyłamy aktualny stan do Alert Managera
                        if alert_manager and enable_alert:
                            msg = f"Channel status mismatch. Current: {channel_status}, Expected: {max_threshold}"
                            alert_manager.process_state(queue_manager, object_name, "STATUS", is_failing, msg, channel_status, enable_alert)
                
                # Schedule next run for this configuration
                config['next_run'] = current_time + config.get('interval', 60)
            
            # Sleep for tick rate before next iteration
            tick_rate = app_config.get('tick_rate', 5)
            time.sleep(tick_rate)
    except KeyboardInterrupt:
        logging.info("Monitoring stopped by user. Shutting down gracefully...")

if __name__ == "__main__":
    main()
