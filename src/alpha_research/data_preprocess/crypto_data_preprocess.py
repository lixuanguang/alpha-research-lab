"""Crypto data preprocessing implementations."""

from __future__ import annotations

import argparse
import logging
import tarfile
from pathlib import Path

import polars as pl

from utils.path_utils import DATA_ROOT

LOGGER = logging.getLogger(__name__)


class OKXOrderBookPreprocessor:
    """Convert OKX order book archives into first-pass Parquet datasets."""

    def __init__(self, input_folder: Path | str, output_folder: Path | str, rolling_window: int = 100, sigma_k: float = 3.0) -> None:
        self.input_folder = Path(input_folder).expanduser().resolve()
        self.output_folder = Path(output_folder).expanduser().resolve()
        self.rolling_window = rolling_window
        self.sigma_k = sigma_k

    def preprocess(self) -> None:
        """Convert one or more OKX order book archives into Parquet files."""

        # Retrieve files
        archives = sorted(path for path in self.input_folder.rglob("*.tar.gz") if path.is_file())
        LOGGER.info("Found %s archive(s) in %s", len(archives), self.input_folder)

        for archive_path in archives:
            LOGGER.info("Processing archive %s", archive_path.name)
            frame = self._archive_to_dataframe(Path(archive_path))
            LOGGER.info("Processed %s event row(s) from %s", frame.height, archive_path.name)


    def _archive_to_dataframe(self, archive_path: Path) -> pl.DataFrame:
        """Read a tar.gz archive containing line-delimited JSON order book events.

        @param archive_path: The path to the tar.gz archive.
        @return: A Polars DataFrame containing the concatenated and normalized order book events
        """

        raw_frames: list[pl.DataFrame] = []
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                LOGGER.debug("Reading member %s from %s", member.name, archive_path.name)
                extracted_file = archive.extractfile(member)
                assert extracted_file is not None
                raw_frame = pl.read_ndjson(extracted_file)
                LOGGER.debug("Loaded %s raw row(s) from %s", raw_frame.height, member.name)
                raw_frames.append(raw_frame)

        frame = pl.concat(raw_frames, how="vertical_relaxed") if len(raw_frames) > 1 else raw_frames[0]
        frame = self._normalize_order_book_schema(frame)
        frame = self._order_order_book_schema(frame)
        frame = self._deduplicate_order_book_schema(frame)
        frame = self._sanity_filter_order_book_schema(frame)
        return self._anchor_to_snapshots(frame)

    def _anchor_to_snapshots(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Discard leading updates until the first snapshot while preserving later snapshots as resync points.

        @param frame: A Polars DataFrame containing flattened events with an "action" column.
        @return: A Polars DataFrame with pre-first-snapshot updates removed.
        """
        snapshot_rows = frame.filter(pl.col("action") == "snapshot")
        first_snapshot_order = snapshot_rows.select(pl.col("order_key").min()).item()
        anchored = frame.filter(pl.col("order_key") >= first_snapshot_order)
        LOGGER.debug("Snapshot anchoring kept %s raw row(s)", anchored.height)
        ordered_columns = [column for column in ["order_key", "event_id", "arrival_order", "sequence_id", "ts", "action", "side", "price", "size"]
                           if column in anchored.columns]
        return anchored.select(ordered_columns)

    def _normalize_order_book_schema(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Flatten OKX order book asks and bids into typed row-wise events.

        @param frame: A Polars DataFrame containing the raw order book events with nested asks and bids.
        @return: A Polars DataFrame with columns [ts, side, price, size] where each row represents a single order book level event.
        """
        LOGGER.debug("Normalizing %s raw row(s)", frame.height)
        frame = frame.with_row_index("event_id")
        action_expr = pl.col("action") if "action" in frame.columns else pl.lit(None).cast(pl.String).alias("action")
        parts: list[pl.DataFrame] = []
        for column, side in (("bids", 1), ("asks", -1)):
            selection = [pl.col("event_id").cast(pl.UInt32), pl.col("ts").cast(pl.Int64), action_expr]
            if "sequence_id" in frame.columns:
                selection.append(pl.col("sequence_id"))
            selection.append(pl.col(column).alias("level"))

            part = frame.select(selection)
            part = part.explode("level")
            part = part.drop_nulls("level")
            selection = [pl.col("event_id"), pl.col("ts"), pl.col("action")]
            if "sequence_id" in part.columns:
                selection.append(pl.col("sequence_id"))
            selection.extend([pl.lit(side).cast(pl.Int8).alias("side"),
                              pl.col("level").list.get(0).cast(pl.Float64).alias("price"),
                              pl.col("level").list.get(1).cast(pl.Float64).alias("size"),])
            part = part.select(selection)
            parts.append(part)

        normalized = pl.concat(parts, how="vertical_relaxed").with_row_index("arrival_order")
        LOGGER.debug("Normalized into %s event row(s)", normalized.height)
        return normalized

    def _deduplicate_order_book_schema(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Apply overwrite and consecutive-duplicate semantics to normalized events.

        @param frame: A Polars DataFrame containing normalized order book events with potential duplicates.
        @return: A Polars DataFrame with duplicates removed
        """
        LOGGER.debug("Deduplicating %s normalized row(s)", frame.height)

        aggregations = [pl.col("size").last().alias("size"),
                        pl.col("order_key").max().alias("order_key"),]
        if "action" in frame.columns:
            aggregations.append(pl.col("action").last().alias("action"))
        if "arrival_order" in frame.columns:
            aggregations.append(pl.col("arrival_order").last().alias("arrival_order"))
        if "sequence_id" in frame.columns:
            aggregations.append(pl.col("sequence_id").last().alias("sequence_id"))

        group_by_columns = [column for column in ["event_id", "ts", "side", "price"] if column in frame.columns]
        frame = frame.group_by(group_by_columns, maintain_order=True).agg(*aggregations)
        frame = frame.sort("order_key")

        duplicate_mask = ((pl.col("side") == pl.col("side").shift(1))
                          & (pl.col("price") == pl.col("price").shift(1))
                          & (pl.col("size") == pl.col("size").shift(1))).fill_null(False)

        deduplicated = frame.filter(~duplicate_mask)
        LOGGER.debug("Deduplicated down to %s row(s)", deduplicated.height)
        return deduplicated

    def _order_order_book_schema(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Sort events by ts and sequence, or by ingestion order when no sequence exists.

        @param frame: A Polars DataFrame containing normalized and deduplicated order book events.
        @return: A Polars DataFrame with events ordered by ts and sequence or ingestion order
        """
        sort_columns = [column for column in ["ts", "sequence_id", "event_id", "arrival_order"] if column in frame.columns]
        ordered = frame.sort(sort_columns).with_row_index("order_key") if sort_columns else frame.with_row_index("order_key")

        if "sequence_id" in frame.columns:
            LOGGER.debug("Ordered %s row(s) by ts and sequence_id", ordered.height)
            return ordered

        LOGGER.debug("Ordered %s row(s) by ts and arrival order", ordered.height)
        return ordered

    def _sanity_filter_order_book_schema(self, frame: pl.DataFrame) -> pl.DataFrame:
        """Drop structurally invalid rows and filter extreme price outliers.

        @param frame: A Polars DataFrame containing normalized, deduplicated, and ordered order book events.
        @return: A Polars DataFrame with invalid and outlier rows removed.
        """
        LOGGER.debug("Applying sanity filters to %s row(s)", frame.height)
        frame = frame.filter((pl.col("price") > 0) & (pl.col("size") >= 0))
        if frame.is_empty():
            LOGGER.debug("All rows removed by structural sanity filters")
            return frame

        frame = frame.with_columns(
            pl.col("price").rolling_median(window_size=self.rolling_window, min_samples=1).alias("rolling_price_median"),
            pl.col("price").rolling_std(window_size=self.rolling_window, min_samples=2).alias("rolling_price_std"),
        )
        frame = frame.filter(
            pl.col("rolling_price_std").is_null()
            | ((pl.col("price") - pl.col("rolling_price_median")).abs() <= self.sigma_k * pl.col("rolling_price_std"))
        )

        filtered = frame.drop("rolling_price_median", "rolling_price_std")
        LOGGER.debug("Sanity filters kept %s row(s)", filtered.height)
        return filtered


def main(data_source: str, data_type: str, info_type: str, inst_type: str, instrument: str, rolling_window: int, sigma_k: float) -> None:
    """
    Main entry point for crypto data preprocessing.

    @param data_source: The source of the data, e.g. "OKX".
    @param data_type: The type of data, e.g. "HISTORICAL", "LIVE".
    @param info_type: The type of information, e.g. "order_book".
    @param inst_type: The type of instrument, e.g. "SPOT", "FUTURES", "SWAP", "OPTION".
    @param instrument: Specific instrument to process, e.g. "BTC-USDT".
    @param rolling_window: Window size for rolling statistics in sanity filtering.
    @param sigma_k: Sigma multiplier for outlier detection in sanity filtering.
    """

    input_folder = DATA_ROOT / "raw" / data_source / data_type / info_type / inst_type / instrument
    output_folder = DATA_ROOT / "processed" / data_source / data_type / info_type / inst_type / instrument

    if data_source == "OKX":
        preprocessor = OKXOrderBookPreprocessor(input_folder=input_folder, output_folder=output_folder, rolling_window=rolling_window, sigma_k=sigma_k,)
    else:
        raise ValueError(f"Unsupported data source: {data_source}")

    preprocessor.preprocess()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Crypto Data Processing")
    parser.add_argument("--data_source", choices=["OKX"], required=True, help="Data source",)
    parser.add_argument("--data_type", choices=["historical", "live"], required=True, help="Data type",)
    parser.add_argument("--info_type", choices=["order_book_400"], required=True, help="Information type",)
    parser.add_argument("--inst_type", choices=["SPOT", "FUTURES", "SWAP", "OPTION"], required=True, help="Instrument type",)
    parser.add_argument("--instrument", required=True, help="Instrument to ingest",)
    parser.add_argument("--rolling_window", type=int, default=100, help="Rolling window size for sanity filtering",)
    parser.add_argument("--sigma_k", type=float, default=3.0, help="Sigma multiplier for outlier detection in sanity filtering",)

    args = parser.parse_args()

    main(args.data_source, args.data_type, args.info_type, args.inst_type, args.instrument, args.rolling_window, args.sigma_k,)
