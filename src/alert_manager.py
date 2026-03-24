import logging
import requests
import urllib3
import json
import time

# Wyłączamy ostrzeżenia o braku certyfikatu SSL (verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class AlertManager:
    def __init__(self, api_url, api_key):
        # Konfiguracja API z parametrów
        self.base_url = api_url
        self.api_key = api_key
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

    def _sync_state_with_api(self):
        """Pobiera z serwera obecnie otwarte alerty przypisane do naszego SRE Daemona, aby uniknąć duplikatów po restarcie skryptu."""
        self.last_sync_attempt = time.time()
        logging.info("--> [ALERT MANAGER] Syncing state with API (looking for open MQ alerts)...")
        search_url = f"{self.base_url}/_search"
        
        payload = {
            "query": {
                # Szukamy tylko otwartych alertów wygenerowanych przez naszą usługę
                "service": "IBM_MQ_MONITOR",
                "status": "open"
            },
            "limit": 100
        }
        
        try:
            response = requests.post(search_url, json=payload, headers=self.headers, verify=False, timeout=10)
            if response.status_code == 200:
                data = response.json()
                alerts = data.get("alerts", [])
                for alert in alerts:
                    res = alert.get("resource")
                    alert_id = alert.get("id")
                    if res and alert_id:
                        self.active_alerts[res] = alert_id
                logging.info(f"--> [ALERT MANAGER] Synced successfully. Found {len(self.active_alerts)} active alerts.")
                self.is_synced = True
            else:
                logging.warning(f"--> [ALERT MANAGER] Failed to sync state. API returned HTTP {response.status_code}")
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
            "service": ["IBM_MQ_MONITOR"],
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
            response = requests.post(self.base_url, json=payload, headers=self.headers, verify=False, timeout=10)
            response.raise_for_status()
            
            # Większość systemów typu Alerta zwraca JSON z ID wygenerowanego alertu.
            # Jeśli API Maximo ma inną strukturę (np. data['alert']['id']), zmodyfikuj poniższą linię:
            response_data = response.json()
            alert_id = response_data.get("id") or response_data.get("alert", {}).get("id")
            
            logging.info(f"--> [MAXIMO API] Created '{severity}' alert for {resource}. ID: {alert_id}")
            return alert_id
            
        except Exception as e:
            logging.error(f"--> [MAXIMO API ERROR] Failed to create alert for {resource}. Error: {e}")
            return None

    def _close_alert(self, alert_id, resource):
        """Wysyła PUT, aby zamknąć istniejący alert za pomocą jego ID."""
        url = f"{self.base_url}/{alert_id}"
        payload = {"status": "closed"}
        
        try:
            response = requests.put(url, json=payload, headers=self.headers, verify=False, timeout=10)
            response.raise_for_status()
            logging.info(f"--> [MAXIMO API] Successfully closed alert {alert_id} for {resource}.")
            return True
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
