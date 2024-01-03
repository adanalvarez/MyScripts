from datetime import datetime
from dateutil.relativedelta import relativedelta
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.security_monitoring_api import SecurityMonitoringApi
from datadog_api_client.v2.model.security_monitoring_signal_list_request import SecurityMonitoringSignalListRequest
from datadog_api_client.v2.model.security_monitoring_signal_list_request_filter import (
    SecurityMonitoringSignalListRequestFilter,
)
from datadog_api_client.v2.model.security_monitoring_signal_list_request_page import (
    SecurityMonitoringSignalListRequestPage,
)
from datadog_api_client.v2.model.security_monitoring_signals_sort import SecurityMonitoringSignalsSort
from datetime import datetime
import statistics
import logging
from typing import List, Tuple, Dict

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_statistics(incident_times: List[float]) -> Dict[str, float]:
    """Calculate statistical metrics of incident times."""
    try:
        incidents_statistics = {
            "max_time": max(incident_times),
            "min_time": min(incident_times),
            "average_time": statistics.mean(incident_times),
            "median_time": statistics.median(incident_times),
            "std_deviation": statistics.stdev(incident_times) if len(incident_times) > 1 else 0
        }

        logging.info("Statistics: " + ", ".join(f"{k}: {v:.2f} minutes" for k, v in incidents_statistics.items()))
        return incidents_statistics
    except statistics.StatisticsError as e:
        logging.error(f"Statistics error: {e}")
        return {}

def get_time_to_close(first_seen: int, archived: int) -> float:
    """Calculate time taken from first seen to archived state."""
    try:
        datetime1 = datetime.utcfromtimestamp(first_seen / 1000.0)
        datetime2 = datetime.utcfromtimestamp(archived / 1000.0)
        time_diff = datetime2 - datetime1
        time_to_close = time_diff.total_seconds() / 60
        logging.debug(f"Time to close: {time_to_close} minutes")
        return time_to_close
    except Exception as e:
        logging.error(f"Error in calculating time to close: {e}")
        return 0

def main():
    """Process security monitoring signals and compute statistics."""
    configuration = Configuration()
    security_metrics = {}
    all_times = []
    severities = ["info", "low", "medium", "high", "critical"]

    for severity in severities:
        times_to_resolve_severity = []

        with ApiClient(configuration) as api_client:
            api_instance = SecurityMonitoringApi(api_client)
            body = SecurityMonitoringSignalListRequest(
                filter=SecurityMonitoringSignalListRequestFilter(
                    _from=(datetime.now() + relativedelta(days=-7)),
                    query=f"status:{severity}",
                    to=datetime.now(),
                ),
                page=SecurityMonitoringSignalListRequestPage(limit=2),
                sort=SecurityMonitoringSignalsSort.TIMESTAMP_ASCENDING,
            )
            try:
                items = api_instance.search_security_monitoring_signals_with_pagination(body=body)
                for item in items:
                    security_alert = item.to_dict()
                    first_seen = security_alert.get("attributes", {}).get("attributes", {}).get("workflow", {}).get("first_seen", {})
                    state_update_timestamp = security_alert.get("attributes", {}).get("attributes", {}).get("workflow", {}).get("triage", {}).get("stateUpdateTimestamp", {})
                    
                    if state_update_timestamp:
                        time_to_close = get_time_to_close(first_seen, state_update_timestamp)
                        times_to_resolve_severity.append(time_to_close)
                        all_times.append(time_to_close)
                    else:
                        logging.info(f"Incident not closed for severity {severity}")

                if times_to_resolve_severity:
                    security_metrics[severity] = get_statistics(times_to_resolve_severity)
            except Exception as e:
                logging.error(f"Error processing signals for severity {severity}: {e}")

    if all_times:
        general_statistics = get_statistics(all_times)
        security_metrics["general"] = general_statistics

    logging.info(f"Overall Metrics: {security_metrics}")
    return security_metrics

if __name__ == "__main__":
    main()
