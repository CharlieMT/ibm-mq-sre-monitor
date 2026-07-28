import subprocess
import re
import logging

class MQConnector:
    def __init__(self, queue_manager):
        self.queue_manager = queue_manager

    def get_ha_status(self, qm_name):
        try:
            cmd = ["dspmq", "-m", qm_name]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            output = result.stdout
            
            if "STATUS(Running as standby)" in output:
                return "STANDBY"
            elif "STATUS(Running)" in output:
                return "ACTIVE"
            else:
                logging.warning(f"Unexpected dspmq output for {qm_name}: {output.strip()}")
                return "UNKNOWN"
                
        except Exception as e:
            logging.error(f"Error checking HA status for {qm_name}: {e}")
            return "ERROR"

    def _run_mqsc(self, command):
        """
        Execute a runmqsc command and return the raw output.
        
        Args:
            command: The MQSC command string to execute (e.g., 'DISPLAY CHANNEL(*)')
        
        Returns:
            Raw stdout string from runmqsc, or empty string on error.
        """
        cmd = f'echo "{command}" | runmqsc {self.queue_manager}'
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if result.returncode != 0 or "not found" in result.stderr.lower():
                logging.error(f"runmqsc command failed: '{command}'. Return code: {result.returncode}, Error: {result.stderr.strip() or result.stdout.strip()}")
                return ""
            return result.stdout
        except Exception as e:
            logging.error(f"Exception executing runmqsc command '{command}': {e}")
            return ""

    def _parse_mqsc_output(self, raw_output):
        """
        Parse runmqsc output into a list of dictionaries.
        
        Each line containing attribute(value) pairs is parsed into a dict.
        Lines starting with 'AMQ' (error/info messages) or empty lines are skipped.
        
        Args:
            raw_output: Raw stdout from runmqsc
        
        Returns:
            List of dicts, each dict representing one object's attributes.
        """
        objects = []
        for line in raw_output.splitlines():
            line = line.strip()
            # Skip empty lines, informational/error messages, and the last line (status)
            if not line or line.startswith('AMQ') or ':' in line[:5]:
                continue
            
            # Parse attribute(value) pairs from the line
            obj = {}
            # Pattern matches: WORD(value) where value can contain anything except closing paren
            pattern = r'(\w+)\(([^)]*)\)'
            matches = re.findall(pattern, line)
            for attr_name, attr_value in matches:
                obj[attr_name] = attr_value.strip()
            
            if obj:
                objects.append(obj)
        
        return objects

    def get_all_channels(self):
        """
        Fetch ALL channel configuration and live telemetry data.
        
        Executes TWO queries against runmqsc:
            1. DISPLAY CHANNEL(*)  - static configuration
            2. DISPLAY CHSTATUS(*)  - dynamic runtime status
        
        Merges the results into a single dictionary keyed by channel name.
        Dynamic attributes from CHSTATUS override/update the static config.
        
        Returns:
            dict: {channel_name: {attr1: val1, attr2: val2, ...}, ...}
                  Returns empty dict if no channels found or on error.
        """
        # Step 1: Fetch static channel configuration
        raw_config = self._run_mqsc('DISPLAY CHANNEL(*)')
        config_objects = self._parse_mqsc_output(raw_config)
        
        # Build dictionary keyed by channel name
        channels = {}
        for obj in config_objects:
            channel_name = obj.get('CHANNEL')
            if channel_name:
                channels[channel_name] = obj
        
        if not channels:
            logging.warning(f"No channels found via DISPLAY CHANNEL(*) on {self.queue_manager}")
            return channels
        
        logging.info(f"Found {len(channels)} channel(s) via DISPLAY CHANNEL(*) on {self.queue_manager}")
        
        # Step 2: Fetch dynamic runtime status
        raw_status = self._run_mqsc('DISPLAY CHSTATUS(*)')
        status_objects = self._parse_mqsc_output(raw_status)
        
        # Merge status data into the channel dictionary
        merged_count = 0
        for status_obj in status_objects:
            channel_name = status_obj.get('CHANNEL')
            if channel_name and channel_name in channels:
                # Merge/update dynamic attributes into the existing channel entry
                channels[channel_name].update(status_obj)
                merged_count += 1
            elif channel_name:
                # Channel has status but no config entry (unusual, but log it)
                logging.debug(f"CHSTATUS found for channel '{channel_name}' but no matching DISPLAY CHANNEL entry")
        
        if merged_count > 0:
            logging.info(f"Merged CHSTATUS data for {merged_count} channel(s) on {self.queue_manager}")
        
        return channels

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
        cmd = f'echo "DISPLAY {mq_object_type}({object_name}) {attribute}" | runmqsc {self.queue_manager}'
        
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

    def get_all_listeners(self):
        """
        Fetch ALL listener configuration and live telemetry data.
        
        Executes TWO queries against runmqsc:
            1. DISPLAY LISTENER(*)  - static configuration
            2. DISPLAY LSSTATUS(*)  - dynamic runtime status
        
        Merges the results into a single dictionary keyed by listener name.
        Dynamic attributes from LSSTATUS override/update the static config.
        
        Returns:
            dict: {listener_name: {attr1: val1, attr2: val2, ...}, ...}
                  Returns empty dict if no listeners found or on error.
        """
        # Step 1: Fetch static listener configuration
        raw_config = self._run_mqsc('DISPLAY LISTENER(*)')
        config_objects = self._parse_mqsc_output(raw_config)
        
        # Build dictionary keyed by listener name
        listeners = {}
        for obj in config_objects:
            listener_name = obj.get('LISTENER')
            if listener_name:
                listeners[listener_name] = obj
        
        if not listeners:
            logging.warning(f"No listeners found via DISPLAY LISTENER(*) on {self.queue_manager}")
            return listeners
        
        logging.info(f"Found {len(listeners)} listener(s) via DISPLAY LISTENER(*) on {self.queue_manager}")
        
        # Step 2: Fetch dynamic runtime status
        raw_status = self._run_mqsc('DISPLAY LSSTATUS(*)')
        status_objects = self._parse_mqsc_output(raw_status)
        
        # Merge status data into the listener dictionary
        merged_count = 0
        for status_obj in status_objects:
            listener_name = status_obj.get('LISTENER')
            if listener_name and listener_name in listeners:
                # Merge/update dynamic attributes into the existing listener entry
                listeners[listener_name].update(status_obj)
                merged_count += 1
            elif listener_name:
                # Listener has status but no config entry (unusual, but log it)
                logging.debug(f"LSSTATUS found for listener '{listener_name}' but no matching DISPLAY LISTENER entry")
        
        if merged_count > 0:
            logging.info(f"Merged LSSTATUS data for {merged_count} listener(s) on {self.queue_manager}")
        
        return listeners

    # Keep old methods for backward compatibility (optional, can be removed later)
    def get_queue_depth(self, queue_name):
        """Backward compatibility method - uses universal get_mq_attribute."""
        return self.get_mq_attribute('QUEUE', queue_name, 'CURDEPTH')

    def get_channel_status(self, channel_name):
        """Backward compatibility method - uses universal get_mq_attribute."""
        return self.get_mq_attribute('CHANNEL', channel_name, 'STATUS')
