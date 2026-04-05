"""OKX ingestion engine."""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import time
from datetime import date
from pathlib import Path
from typing import Any, cast
from urllib import error, request

from fastapi import logger
import polars as pl

import utils.config_loader as config_loader
import utils.datetime_utils as datetime_utils
from utils.path_utils import DATA_ROOT, VENUE_CONFIG_ROOT

LOGGER = logging.getLogger(__name__)


class OKXIngestion:

    def __init__(self, instrument: list[str], download_data_types: list[str], start_date: str | None, end_date: str | None, inst_type: str) -> None:
        '''
        Initialize the OKX ingestion engine.

        @param instrument: Instruments to query.
        @param download_data_types: OKX data types to request.
        @param start_date: Start date in YYYYMMDD format.
        @param end_date: End date in YYYYMMDD format.
        @param inst_type: OKX instrument type.
        @return: None.
        '''
        self.instrument = instrument
        self.download_data_types = download_data_types
        self.start_date = start_date
        self.end_date = end_date
        self.inst_type = inst_type
        self.venue_config = config_loader.load_yaml(VENUE_CONFIG_ROOT / "okx.yaml")

    def download_data(self) -> pl.DataFrame:
        '''
        Fetch available OKX files and download missing ones.

        @param: None.
        @return: A Polars dataframe of discovered files and download flags.
        '''
        LOGGER.info("Starting OKX ingestion for %s data type(s)", len(self.download_data_types))
        available_files = [self._fetch_available_file_urls(data_type) for data_type in self.download_data_types]
        if not available_files:
            return pl.DataFrame(
                schema={
                    "data_type": pl.String,
                    "inst_type": pl.String,
                    "instrument": pl.String,
                    "url": pl.String,
                    "timestamp": pl.String,
                    "local_path": pl.String,
                    "To Download": pl.Boolean,
                }
            )

        available_files_df = pl.concat(available_files, how="vertical").with_columns(
            pl.col("url").map_elements(lambda url: not self._check_data_existence(url), return_dtype=pl.Boolean).alias("To Download")
        )
        total_rows = available_files_df.height
        total_to_download = available_files_df.filter(pl.col("To Download")).height
        LOGGER.info("Discovered %s file(s); %s file(s) need download", total_rows, total_to_download)

        for row in available_files_df.filter(pl.col("To Download")).iter_rows(named=True):
            target_path = Path(row["local_path"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            self._download_file(row["url"], target_path)

        LOGGER.info("OKX ingestion finished")
        return available_files_df

    def _fetch_available_file_urls(self, data_type: str) -> pl.DataFrame:
        '''
        Request and parse available file URLs for one OKX data type.

        @param data_type: OKX data type to request.
        @return: A Polars dataframe of discovered files.
        '''
        start_date, end_date = self._resolve_date_range(data_type)
        LOGGER.info("Fetching %s from %s to %s", data_type, start_date, end_date)
        rows: list[dict[str, str]] = []
        current_start_date = start_date
        chunk_index = 1

        while current_start_date <= end_date:
            current_end_date = min(datetime_utils.shift_date(current_start_date, days=20), end_date)
            LOGGER.info("Requesting %s chunk %s: %s to %s", data_type, chunk_index, current_start_date, current_end_date)
            response_data = self._request_download_data(data_type, current_start_date, current_end_date)
            details = cast("list[dict[str, Any]]", response_data.get("details", []))
            before_count = len(rows)
            rows.extend(
                {
                    "data_type": data_type,
                    "inst_type": self.inst_type,
                    "instrument": detail.get("instId") or detail.get("instFamily") or detail.get("ccy") or "",
                    "url": url_value,
                    "timestamp": datetime_utils.timestamp_ms_to_string(date_ts),
                    "local_path": self._set_download_to_local_path(data_type, detail.get("instId") or detail.get("instFamily") or detail.get("ccy") or "", url_value),
                }
                for detail in details
                for group_detail in cast("list[dict[str, Any]]", detail.get("groupDetails", []))
                if isinstance((url_value := group_detail.get("url")), str)
                and (date_ts := group_detail.get("dateTs")) is not None
            )
            LOGGER.info("Received %s file(s) for %s chunk %s", len(rows) - before_count, data_type, chunk_index)
            current_start_date = datetime_utils.shift_date(current_end_date)
            chunk_index += 1

        LOGGER.info("Finished %s with %s discovered file(s)", data_type, len(rows))

        return pl.DataFrame(
            rows,
            schema={"data_type": pl.String, "inst_type": pl.String, "instrument": pl.String, "url": pl.String, "timestamp": pl.String, "local_path": pl.String},
        )

    def _request_download_data(self, data_type: str, start_date: str, end_date: str) -> dict[str, Any]:
        '''
        Request OKX download metadata for a date range.

        @param data_type: OKX data type to request.
        @param start_date: Start date in YYYYMMDD format.
        @param end_date: End date in YYYYMMDD format.
        @return: The OKX response data payload.
        '''
        api_config = self.venue_config["historical_data_api"]
        module_config = api_config["modules"][data_type]
        endpoint = api_config["endpoints"]["download_link"]["path"]
        url = f"{api_config['base_url']}/{endpoint}"
        headers = {key: str(value) for key, value in api_config["headers"].items()}
        payload = {
            "module": module_config["id"],
            "instType": self.inst_type,
            "instQueryParam": self._build_inst_query_param(data_type),
            "dateQuery": {
                "dateAggrType": "daily",
                "begin": datetime_utils.to_timestamp_ms(start_date),
                "end": datetime_utils.to_timestamp_ms(datetime_utils.shift_date(end_date)),
            },
        }

        http_request = request.Request(url=url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")

        for attempt in range(5):
            try:
                with request.urlopen(http_request, timeout=30) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                    if not isinstance(response_payload, dict):
                        return {}
                    response_data = response_payload.get("data", {})
                    return response_data if isinstance(response_data, dict) else {}
            except error.HTTPError as exc:
                if exc.code != 429 or attempt == 4:
                    raise
                retry_after = exc.headers.get("Retry-After")
                LOGGER.warning("Rate limited fetching %s for %s to %s; retrying", data_type, start_date, end_date)
                time.sleep(int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)

        return {}

    def _build_inst_query_param(self, data_type: str) -> dict[str, list[str]]:
        '''
        Build the OKX instQueryParam payload.

        @param data_type: OKX data type to request.
        @return: A query-parameter dictionary for the API request.
        '''
        overrides = self.venue_config["historical_data_api"]["modules"][data_type].get("overrides", {})
        override = overrides.get("daily", {}).get("inst_query_param")

        if override is not None:
            key = override["key"]
            query_values = [instrument.split("-", maxsplit=1)[0] for instrument in self.instrument] if key == "ccyList" else self.instrument
            return {key: override.get("value", query_values)}

        key = self.venue_config["historical_data_api"]["inst_query_param"][self.inst_type]["key"]
        query_values = [instrument.split("-", maxsplit=1)[0] for instrument in self.instrument] if key == "ccyList" else self.instrument
        return {key: query_values}

    def _resolve_date_range(self, data_type: str) -> tuple[str, str]:
        '''
        Resolve the effective date range for a data type.

        @param data_type: OKX data type to request.
        @return: Start and end dates in YYYYMMDD format.
        '''
        if self.start_date is not None and self.end_date is not None:
            LOGGER.info("Using explicit date range %s to %s for %s", self.start_date, self.end_date, data_type)
            return str(self.start_date), str(self.end_date)

        hint_start_date = self.venue_config["historical_data_api"]["modules"][data_type]["available_since"].replace("-", "")
        end_date = date.today().strftime("%Y%m%d")
        LOGGER.info("Resolving earliest available date for %s using hint %s", data_type, hint_start_date)
        return self._resolve_earliest_available_date(data_type, hint_start_date, end_date), end_date

    def _resolve_earliest_available_date(self, data_type: str, hint_start_date: str, end_date: str) -> str:
        '''
        Resolve the earliest available date using a config hint and light probing.

        @param data_type: OKX data type to request.
        @param hint_start_date: Configured earliest candidate date.
        @param end_date: Upper date bound in YYYYMMDD format.
        @return: Earliest discovered date in YYYYMMDD format.
        '''
        current_start_date = hint_start_date
        probe_index = 1

        while current_start_date <= end_date:
            current_end_date = min(datetime_utils.shift_date(current_start_date, days=30), end_date)
            LOGGER.info("Probing %s availability window %s: %s to %s", data_type, probe_index, current_start_date, current_end_date)
            response_data = self._request_download_data(data_type, current_start_date, current_end_date)
            details = cast("list[dict[str, Any]]", response_data.get("details", []))
            first_date_ts = min(
                (
                    int(group_detail["dateTs"])
                    for detail in details
                    for group_detail in cast("list[dict[str, Any]]", detail.get("groupDetails", []))
                    if group_detail.get("dateTs") is not None
                ),
                default=None,
            )
            if first_date_ts is not None:
                resolved_date = datetime_utils.timestamp_ms_to_string(first_date_ts, fmt="%Y%m%d")
                LOGGER.info("Resolved earliest %s date to %s", data_type, resolved_date)
                return resolved_date
            current_start_date = datetime_utils.shift_date(current_end_date)
            probe_index += 1

        LOGGER.info("No earlier %s data found; falling back to hint %s", data_type, hint_start_date)
        return hint_start_date

    def _check_data_existence(self, url: str) -> bool:
        '''
        Check whether data already exists locally.

        @param url: File URL to check.
        @return: Whether the data already exists.
        '''
        if not DATA_ROOT.exists():
            return False

        file_name = url.rsplit("/", maxsplit=1)[-1]
        return any(path.name == file_name for path in DATA_ROOT.rglob("*") if path.is_file())

    def _set_download_to_local_path(self, data_type: str, instrument: str, url: str) -> str:
        '''
        Build the local relative target path under /data.

        @param data_type: OKX data type.
        @param instrument: Instrument or family name.
        @param url: File URL.
        @return: Relative target path from /data.
        '''
        file_name = url.rsplit("/", maxsplit=1)[-1]
        instrument_dir = instrument or "all"
        return f"{DATA_ROOT}/raw/OKX/historical/{data_type}/{self.inst_type}/{instrument_dir}/{file_name}"

    def _download_file(self, url: str, target_path: Path) -> None:
        '''
        Download a file to a local path with simple 429 retry handling.

        @param url: File URL to download.
        @param target_path: Local file path.
        @return: None.
        '''
        for attempt in range(5):
            try:
                LOGGER.info("Downloading %s", target_path.name)
                with request.urlopen(url, timeout=300) as response, target_path.open("wb") as file_handle:
                    shutil.copyfileobj(response, file_handle)
                LOGGER.info("Saved %s", target_path)
                return
            except error.HTTPError as exc:
                if exc.code != 429 or attempt == 4:
                    raise
                retry_after = exc.headers.get("Retry-After")
                LOGGER.warning("Rate limited downloading %s; retrying", target_path.name)
                time.sleep(int(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)


if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="OKX ingestion engine")
    parser.add_argument("--instrument", nargs="*", default=[], help="Instrument(s) to ingest, e.g. BTC-USDT ETH-USDT",)
    parser.add_argument("--download_data_types", nargs="*", required=True, help="Data types to download, e.g. trade_history funding_rates",)
    parser.add_argument("--inst_type", choices=["SPOT", "FUTURES", "SWAP", "OPTION"], required=True, help="OKX instrument type",)

    date_mode_group = parser.add_mutually_exclusive_group(required=True)
    date_mode_group.add_argument("--download_all_data", action="store_true", help="Download all available data using the widest configured date range",)
    date_mode_group.add_argument("--date_range", nargs=2, metavar=("START_DATE", "END_DATE"), type=lambda s: s.replace("-", ""), help="Start and end dates in YYYYMMDD format",)

    args = parser.parse_args()

    start_date, end_date = (args.date_range if args.date_range else (None, None))

    ingestion = OKXIngestion(args.instrument, args.download_data_types, start_date, end_date, args.inst_type,)
    logging.info("OKX ingestion returned %s discovered file(s)", ingestion.download_data().height)