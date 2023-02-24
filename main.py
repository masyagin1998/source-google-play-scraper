#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#


import sys

from airbyte_cdk.entrypoint import launch
from source_google_play_scraper import SourceGooglePlayScraper

if __name__ == "__main__":
    source = SourceGooglePlayScraper()
    launch(source, sys.argv[1:])
