import subprocess
import re
import logging

class MQConnector:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

    def get_mq_attribute(self, object_type, object_name, attribute):
        """
        Universal method to get any MQ attribute.
        
        Args:
            object_type: Either 'QUEUE' or 'CHANNEL'
            object_name: Name of the queue or channel
            attribute: The attribute to retrieve (e.g., 'CURDEPTH', 'STATUS', 'MAXDEPTH', etc.)
        
        Returns:
            The attribute value as string, or None if not found or error.
        """
        # Map object_type to MQ command object type
        type_map = {
            'QUEUE': 'QUEUE',
            'CHANNEL': 'CHL'
        }
        
        mq_object_type = type_map.get(object_type.upper(), object_type.upper())
        
        # Build the MQSC command
        cmd = f'echo "DISPLAY {mq_object_type}({object_name}) {attribute}" | ./runmqsc {self.queue_manager}'
        
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            
            # Check for system-level errors (command not found, permission denied, etc.)
            if result.returncode != 0 or "not found" in result.stderr.lower() or "not found" in result.stdout.lower():
                logging.error(f"Command failed for {object_type} '{object_name}'. Return code: {result.returncode}, Output: {result.stderr.strip() or result.stdout.strip()}")
                return None
            
            # Command succeeded (returncode == 0), now search for the attribute
            # Use regex to extract attribute value: attribute(value)
            # The regex pattern matches: attribute(any characters except closing parenthesis)
            pattern = rf"{re.escape(attribute)}\(([^)]+)\)"
            match = re.search(pattern, result.stdout)
            
            if match:
                value = match.group(1).strip()
                logging.debug(f"Found attribute '{attribute}' for {object_type} '{object_name}': {value}")
                return value
            else:
                # Attribute not found in output
                logging.warning(f"Attribute '{attribute}' not found in MQ output for {object_type} '{object_name}'. Output: {result.stdout.strip()}")
                return None
                
        except Exception as e:
            logging.error(f"Exception while getting attribute '{attribute}' for {object_type} '{object_name}': {e}")
            return None

    # Keep old methods for backward compatibility (optional, can be removed later)
    def get_queue_depth(self, queue_name):
        """Backward compatibility method - uses universal get_mq_attribute."""
        return self.get_mq_attribute('QUEUE', queue_name, 'CURDEPTH')

    def get_channel_status(self, channel_name):
        """Backward compatibility method - uses universal get_mq_attribute."""
        return self.get_mq_attribute('CHANNEL', channel_name, 'STATUS')
