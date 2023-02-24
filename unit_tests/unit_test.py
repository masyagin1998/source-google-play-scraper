import json

import pytest
from airbyte_cdk.models import SyncMode
from jsonschema import validate

from source_google_play_scraper.source import SourceGooglePlayScraper

sample_config = {
    "app_id": "taxi.android.client",
    "languages": {
        "type": "all"
    },
    "start_date": "2022-01-01",
    "timeout_milliseconds": 1000,
    "max_reviews_per_request": 100
}


@pytest.mark.parametrize(
    "config",
    [
        sample_config
    ],
)
def test_google_play_scraper_reviews_stream(config):
    reviews = SourceGooglePlayScraper().streams(config)[0]
    record_schema = json.load(open("./source_google_play_scraper/schemas/reviews.json"))
    for record in reviews.read_records(SyncMode.full_refresh):
        assert (validate(record, record_schema) is None)
