import logging
import json
import time
import subprocess
import ssl
import urllib.request
import urllib.error

class AlertManager:
    def __init__(self, api_url, api_key, service_name='IBM_MQ_MONITOR', http_backend='urllib'):
        # Konfiguracja API z parametrów
        self.base_url = api_url
        self.api_key = api_key
        self.service_name = service_name
        self.http_backend = http_backend.lower()
        self.headers = {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }
        
        # Pamięć RAM: mapowanie 'Zasób' -> 'ID Alertu' (np. 'QM1:LOCAL.QUEUE.TEST' -> '5hf545udf...')
        self.active_alerts = {}
        
        # Circuit breaker / fail-safe mechanism
        self.is_synced = False
        self.last_sync_attempt = 0
        self.sync_retry_interval = 300  # 5 minutes in seconds
        
        # Przy starcie daemona, odbudowujemy stan z serwera (State Recovery)
        self._sync_state_with_api()

    def _send_http_request(self, method, url, payload=None):
        """
        Send HTTP request using the configured backend.
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: Full URL to request
            payload: Optional JSON payload for POST/PUT requests
        
        Returns:
            Tuple of (status_code, response_data) where response_data is parsed JSON or None
        """
        try:
            if self.http_backend == 'urllib':
                # Native Python urllib backend (no external dependencies)
                import urllib.request
                import ssl
                
                # Create unverified SSL context to replicate verify=False
                context = ssl._create_unverified_context()
                
                # Prepare request
                headers = {**self.headers}
                if payload is not None:
                    data = json.dumps(payload).encode('utf-8')
                else:
                    data = None
                
                req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
                
                try:
                    with urllib.request.urlopen(req, context=context, timeout=10) as response:
                        status_code = response.getcode()
                        response_body = response.read().decode('utf-8')
                        if response_body:
                            response_data = json.loads(response_body)
                        else:
                            response_data = {}
                        return status_code, response_data
                except urllib.error.HTTPError as e:
                    # HTTPError has status code and response body
                    status_code = e.code
                    try:
                        response_body = e.read().decode('utf-8')
                        response_data = json.loads(response_body) if response_body else {}
                    except:
                        response_data = {}
                    return status_code, response_data
                    
            elif self.http_backend == 'curl':
                # System curl backend
                headers_list = []
                for key, value in self.headers.items():
                    headers_list.append(f'-H "{key}: {value}"')
                
                headers_str = ' '.join(headers_list)
                
                if payload is not None:
                    payload_json = json.dumps(payload)
                    # Escape quotes for shell
                    payload_json_escaped = payload_json.replace('"', '\\"')
                    data_arg = f'-d "{payload_json_escaped}"'
                else:
                    data_arg = ''
                
                cmd = f'curl -s -k -X {method.upper()} {headers_str} {data_arg} "{url}"'
                
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    try:
                        response_data = json.loads(result.stdout) if result.stdout else {}
                        # curl doesn't give us status code directly, assume 200 for success
                        return 200, response_data
                    except json.JSONDecodeError:
                        logging.error(f"Failed to parse curl response as JSON: {result.stdout[:100]}")
                        return 500, None
                else:
                    logging.error(f"curl command failed with return code {result.returncode}: {result.stderr}")
                    return 500, None
                    
            elif self.http_backend == 'requests':
                # Legacy requests backend (requires pip install)
                try:
                    import requests
                    # Disable SSL warnings for requests
                    import urllib3
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
                except ImportError:
                    logging.error("Requests backend selected but 'requests' module not available. Falling back to urllib.")
                    self.http_backend = 'urllib'
                    return self._send_http_request(method, url, payload)
                
                try:
                    response = requests.request(
                        method.upper(),
                        url,
                        json=payload,
                        headers=self.headers,
                        verify=False,
                        timeout=10
                    )
                    status_code = response.status_code
                    try:
                        response_data = response.json() if response.content else {}
                    except:
                        response_data = {}
                    return status_code, response_data
                except Exception as e:
                    logging.error(f"Requests backend error: {e}")
                    return 500, None
                    
            else:
                logging.error(f"Unknown HTTP backend: {self.http_backend}. Falling back to urllib.")
                self.http_backend = 'urllib'
                return self._send_http_request(method, url, payload)
                
        except Exception as e:
            logging.error(f"HTTP request failed with backend '{self.http_backend}': {e}")
            return 500, None

    def _sync_state_with_api(self):
        """Pobiera z serwera obecnie otwarte alerty przypisane do naszego SRE Daemona, aby uniknąć duplikatów po restarcie skryptu."""
        self.last_sync_attempt = time.time()
        logging.info(f"--> [ALERT MANAGER] Syncing state with API (looking for open alerts for service '{self.service_name}') with backend '{self.http_backend}'...")
        search_url = f"{self.base_url}/_search"
        
        payload = {
            "query": {
                # Szukamy tylko otwartych alertów wygenerowanych przez naszą usługę
                "service": self.service_name,
                "status": "open"
            },
            "limit": 100
        }
        
        try:
            status_code, response_data = self._send_http_request('POST', search_url, payload)
            if status_code == 200:
                # --- ZABEZPIECZENIE TYPU DANYCH Z API ---
                alerts = []
                if isinstance(response_data, list):
                    # Jeśli Maximo rzuca czystą listą
                    alerts = response_data
                elif isinstance(response_data, dict):
                    # Jeśli Maximo rzuca słownikiem
                    alerts = response_data.get("alerts", response_data.get("data", []))
                else:
                    logging.warning(f"--> [ALERT MANAGER] Otrzymano nieznany format z API: {type(response_data)}")
                
                # Przetwarzanie wyciągniętych alertów
                for alert in alerts:
                    if isinstance(alert, dict): # Upewniamy się, że element jest poprawny
                        res = alert.get("resource")
                        alert_id = alert.get("id")
                        if res and alert_id:
                            self.active_alerts[res] = alert_id
                            
                logging.info(f"--> [ALERT MANAGER] Synced successfully. Found {len(self.active_alerts)} active alerts for service '{self.service_name}'.")
                self.is_synced = True
            else:
                logging.warning(f"--> [ALERT MANAGER] Failed to sync state. API returned HTTP {status_code}")
                self.is_synced = False
        except Exception as e:
            logging.error(f"--> [ALERT MANAGER] Exception during state sync: {e}")
            self.is_synced = False

    def _create_alert(self, severity, resource, event, value, message):
        """Wysyła POST, aby utworzyć nowy alert. Zwraca wygenerowane ID alertu lub None."""
        # Circuit breaker: check if state is synced before creating new alerts
        if not self.is_synced:
            logging.warning(f"--> [ALERT MANAGER] Cannot open new alert for {resource}: State is not synced with API to prevent duplicates")
            return None
        
        # Jeśli to awaria, zlecamy Maximo automatyczne utworzenie incydentu na 1. linię wsparcia
        auto_create_incident = severity in ["major", "critical"]
        
        payload = {
            "severity": severity,
            "resource": resource,
            "event": event,
            "value": value,
            "message": message,
            "service": [self.service_name],
            "attributes": {
                "snap": {
                    "incident": {
                        "first_line": "Operation Center",
                        "auto_create": auto_create_incident
                    }
                }
            }
        }

        try:
            status_code, response_data = self._send_http_request('POST', self.base_url, payload)
            if status_code in [200, 201]:  # 200 OK or 201 Created
                # Większość systemów typu Alerta zwraca JSON z ID wygenerowanego alertu.
                # Jeśli API Maximo ma inną strukturę (np. data['alert']['id']), zmodyfikuj poniższą linię:
                alert_id = response_data.get("id") or response_data.get("alert", {}).get("id")
                
                if alert_id:
                    logging.info(f"--> [MAXIMO API] Created '{severity}' alert for service '{self.service_name}', resource {resource}. ID: {alert_id}")
                    return alert_id
                else:
                    logging.error(f"--> [MAXIMO API ERROR] Alert created but no ID returned in response: {response_data}")
                    return None
            else:
                logging.error(f"--> [MAXIMO API ERROR] Failed to create alert for {resource}. HTTP {status_code}")
                return None
            
        except Exception as e:
            logging.error(f"--> [MAXIMO API ERROR] Failed to create alert for {resource}. Error: {e}")
            return None

    def _close_alert(self, alert_id, resource):
        """Wysyła PUT, aby zamknąć istniejący alert za pomocą jego ID."""
        url = f"{self.base_url}/{alert_id}"
        payload = {"status": "closed"}
        
        try:
            status_code, response_data = self._send_http_request('PUT', url, payload)
            if status_code in [200, 204]:  # 200 OK or 204 No Content
                logging.info(f"--> [MAXIMO API] Successfully closed alert {alert_id} for {resource}.")
                return True
            else:
                logging.error(f"--> [MAXIMO API ERROR] Failed to close alert {alert_id}. HTTP {status_code}")
                return False
        except Exception as e:
            logging.error(f"--> [MAXIMO API ERROR] Failed to close alert {alert_id}. Error: {e}")
            return False

    def process_state(self, queue_manager, object_name, check_type, is_failing, message, value, enable_alert, severity='major'):
        """Główna metoda wywoływana z pętli zdarzeń. Decyduje o akcji na podstawie pamięci (stanu)."""
        if not enable_alert:
            return

        # Optional: Try to re-sync if not synced and enough time has passed
        if not self.is_synced and (time.time() - self.last_sync_attempt) > self.sync_retry_interval:
            logging.info("--> [ALERT MANAGER] Attempting to re-sync state with API...")
            self._sync_state_with_api()

        resource = f"{queue_manager}:{object_name}"
        event = check_type # 'CURDEPTH' lub 'STATUS' lub any other attribute

        # SCENARIUSZ 1: Awaria, o której jeszcze nie wie Maximo
        if is_failing and resource not in self.active_alerts:
            # For CLI connection errors, override with 'critical' as specified in requirements
            # Otherwise use the passed severity parameter
            final_severity = "critical" if "CLI" in message else severity
            
            alert_id = self._create_alert(final_severity, resource, event, value, message)
            if alert_id:
                # Zapisujemy ID alertu do pamięci
                self.active_alerts[resource] = alert_id

        # SCENARIUSZ 2: Naprawiono. Kolejka jest w normie, ale mamy otwarty ticket w pamięci
        elif not is_failing and resource in self.active_alerts:
            alert_id = self.active_alerts[resource]
            
            success = self._close_alert(alert_id, resource)
            if success:
                # Usuwamy z pamięci, by być gotowym na kolejne problemy
                del self.active_alerts[resource]
