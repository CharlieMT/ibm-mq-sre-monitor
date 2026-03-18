import subprocess
import re
import logging

class MQConnector:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

    def get_queue_depth(self, queue_name):
        cmd = f'echo "DISPLAY QUEUE({queue_name})" | runmqsc {self.queue_manager}'
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            # Check for system-level errors (command not found, permission denied, etc.)
            if result.returncode != 0 or "not found" in result.stderr.lower() or "not found" in result.stdout.lower():
                logging.error(f"Command failed for queue '{queue_name}'. Return code: {result.returncode}, Output: {result.stderr.strip() or result.stdout.strip()}")
                return None
            
            # Command succeeded (returncode == 0), now search for CURDEPTH
            match = re.search(r'CURDEPTH\((\d+)\)', result.stdout)
            if match:
                return int(match.group(1))
            else:
                # CURDEPTH not found in output - this could be a warning or object doesn't exist
                logging.warning(f"Unexpected MQ output for queue '{queue_name}': {result.stdout.strip()}")
                return None
        except Exception as e:
            logging.error(f"Exception while getting queue depth for '{queue_name}': {e}")
            return None

    def get_channel_status(self, channel_name):
        cmd = f'echo "DISPLAY CHL({channel_name})" | runmqsc {self.queue_manager}'
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            # Check for system-level errors (command not found, permission denied, etc.)
            if result.returncode != 0 or "not found" in result.stderr.lower() or "not found" in result.stdout.lower():
                logging.error(f"Command failed for channel '{channel_name}'. Return code: {result.returncode}, Output: {result.stderr.strip() or result.stdout.strip()}")
                return None
            
            # Command succeeded (returncode == 0), now search for STATUS
            match = re.search(r'STATUS\((\w+)\)', result.stdout)
            if match:
                return match.group(1)
            else:
                # STATUS not found in output - this could be a warning or object doesn't exist
                logging.warning(f"Unexpected MQ output for channel '{channel_name}': {result.stdout.strip()}")
                return None
        except Exception as e:
            logging.error(f"Exception while getting channel status for '{channel_name}': {e}")
            return None
