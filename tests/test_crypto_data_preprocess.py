import polars as pl

from alpha_research.data_preprocess.crypto_data_preprocess import OKXOrderBookPreprocessor


def test_anchor_to_snapshots_discards_updates_before_first_snapshot() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".")
    frame = pl.DataFrame(
        {
            "action": ["update", "update", "snapshot", "update", "snapshot", "update"],
            "order_key": [0, 1, 2, 3, 4, 5],
            "ts": [1, 2, 3, 4, 5, 6],
            "side": [1, 1, 1, 1, -1, -1],
            "price": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0],
            "size": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )

    anchored = preprocessor._anchor_to_snapshots(frame)

    assert anchored["action"].to_list() == ["snapshot", "update", "snapshot", "update"]
    assert anchored["ts"].to_list() == [3, 4, 5, 6]


def test_normalize_order_book_schema_flattens_order_book_levels() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".")
    frame = pl.DataFrame(
        {
            "ts": ["1735776000009", "1735776000019"],
            "asks": [[[
                "94589.5",
                "0.48029285",
                "8",
            ]], []],
            "bids": [[[
                "94589.4",
                "0.06610058",
                "5",
            ], [
                "94589.3",
                "0.12340000",
                "1",
            ]], [[
                "94562.5",
                "0.16572182",
                "1",
            ]]],
        }
    )

    normalized = preprocessor._normalize_order_book_schema(frame)

    assert normalized.columns == ["arrival_order", "event_id", "ts", "action", "side", "price", "size"]
    assert normalized.schema == {
        "arrival_order": pl.UInt32,
        "event_id": pl.UInt32,
        "ts": pl.Int64,
        "action": pl.String,
        "side": pl.Int8,
        "price": pl.Float64,
        "size": pl.Float64,
    }
    assert normalized.select("event_id", "ts", "action", "side", "price", "size").to_dicts() == [
        {"event_id": 0, "ts": 1735776000009, "action": None, "side": 1, "price": 94589.4, "size": 0.06610058},
        {"event_id": 0, "ts": 1735776000009, "action": None, "side": 1, "price": 94589.3, "size": 0.1234},
        {"event_id": 1, "ts": 1735776000019, "action": None, "side": 1, "price": 94562.5, "size": 0.16572182},
        {"event_id": 0, "ts": 1735776000009, "action": None, "side": -1, "price": 94589.5, "size": 0.48029285},
    ]


def test_deduplicate_order_book_schema_applies_consistency_rules() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".")
    frame = pl.DataFrame(
        {
            "ts": [1, 1, 2, 3, 4, 4],
            "side": [1, 1, 1, 1, -1, -1],
            "price": [100.0, 100.0, 100.0, 100.0, 101.0, 101.0],
            "size": [1.0, 2.0, 2.0, 3.0, 5.0, 5.0],
        }
    )

    deduplicated = preprocessor._deduplicate_order_book_schema(frame)

    assert deduplicated.select("ts", "side", "price", "size").to_dicts() == [
        {"ts": 1, "side": 1, "price": 100.0, "size": 2.0},
        {"ts": 3, "side": 1, "price": 100.0, "size": 3.0},
        {"ts": 4, "side": -1, "price": 101.0, "size": 5.0},
    ]


def test_order_order_book_schema_sorts_by_ts_then_ingestion_order() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".")
    frame = pl.DataFrame(
        {
            "ts": [3, 1, 1, 2],
            "event_id": [3, 1, 1, 2],
            "arrival_order": [3, 1, 2, 4],
            "side": [1, 1, -1, 1],
            "price": [103.0, 101.0, 102.0, 104.0],
            "size": [3.0, 1.0, 2.0, 4.0],
        }
    )

    ordered = preprocessor._order_order_book_schema(frame)

    assert ordered.select("ts", "side", "price", "size").to_dicts() == [
        {"ts": 1, "side": 1, "price": 101.0, "size": 1.0},
        {"ts": 1, "side": -1, "price": 102.0, "size": 2.0},
        {"ts": 2, "side": 1, "price": 104.0, "size": 4.0},
        {"ts": 3, "side": 1, "price": 103.0, "size": 3.0},
    ]


def test_order_order_book_schema_prefers_sequence_id_when_present() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".")
    frame = pl.DataFrame(
        {
            "ts": [1, 1, 1],
            "sequence_id": [30, 10, 20],
            "event_id": [0, 0, 0],
            "arrival_order": [0, 1, 2],
            "side": [1, 1, 1],
            "price": [103.0, 101.0, 102.0],
            "size": [3.0, 1.0, 2.0],
        }
    )

    ordered = preprocessor._order_order_book_schema(frame)

    assert ordered.select("sequence_id", "price").to_dicts() == [
        {"sequence_id": 10, "price": 101.0},
        {"sequence_id": 20, "price": 102.0},
        {"sequence_id": 30, "price": 103.0},
    ]


def test_sanity_filter_order_book_schema_drops_invalid_and_outlier_rows() -> None:
    preprocessor = OKXOrderBookPreprocessor(input_folder=".", output_folder=".", rolling_window=3, sigma_k=1.0)
    frame = pl.DataFrame(
        {
            "ts": [1, 2, 3, 4, 5, 6],
            "side": [1, 1, 1, 1, 1, 1],
            "price": [100.0, 101.0, 0.0, 102.0, 1000.0, 101.5],
            "size": [1.0, 1.0, 1.0, -1.0, 1.0, 1.0],
        }
    )

    filtered = preprocessor._sanity_filter_order_book_schema(frame)

    assert filtered.to_dicts() == [
        {"ts": 1, "side": 1, "price": 100.0, "size": 1.0},
        {"ts": 2, "side": 1, "price": 101.0, "size": 1.0},
        {"ts": 6, "side": 1, "price": 101.5, "size": 1.0},
    ]



