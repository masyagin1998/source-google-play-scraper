#
# Copyright (c) 2022 Airbyte, Inc., all rights reserved.
#


import json
from copy import deepcopy
from datetime import datetime
from time import sleep
from typing import Any, Iterable, List, Mapping, MutableMapping, Optional, Tuple, Union

import requests
from airbyte_cdk import AirbyteLogger
from airbyte_cdk.sources import AbstractSource
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.http import HttpStream
from google_play_scraper import Sort as GooglePlaySort
from google_play_scraper.constants.element import ElementSpecs as GooglePlayElementSpecs
from google_play_scraper.constants.regex import Regex as GooglePlayRegex
from google_play_scraper.constants.request import Formats as GooglePlayFormats

URL_BASE = "https://play.google.com"

ALL_LANGUAGES = ['af', 'am', 'ar', 'bg', 'ca', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fil', 'fr', 'he', 'hi', 'hr', 'hu', 'id',
                 'is', 'it', 'ja', 'ko', 'lt', 'lv', 'ms', 'nl', 'no', 'pl', 'pt', 'ro', 'ru', 'sk', 'sl', 'sr', 'sv', 'sw', 'th', 'tr',
                 'uk', 'vi', 'zh', 'zh_hk', 'zu']

END_TOKEN = ["end", "token"]


class Reviews(HttpStream):
    url_base = URL_BASE
    primary_key = 'reviewId'
    cursor_field = 'at'

    @staticmethod
    def __datetime_to_str(d: datetime) -> str:
        return d.strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def __str_to_datetime(d: str) -> datetime:
        return datetime.strptime(d, "%Y-%m-%dT%H:%M:%S")

    # noinspection PyUnusedLocal
    def __init__(self, config, **kwargs):
        super().__init__()
        self.__config = config

        self.__logger = AirbyteLogger()

        self.__language_ind = 0
        self.__languages = self.__config['languages']['selected']

        self.__count_in_req = 0
        self.__count = 0
        self.__total_count = 0

        self.__cursor_value = datetime.strptime(self.__config['start_date'], "%Y-%m-%d")
        self.__tmp_cursor_value = self.__cursor_value

        self.__logger.info("Read latest reviews timestamp from config: {}".format(self.__datetime_to_str(self.__cursor_value)))

    @property
    def state(self) -> Mapping[str, Any]:
        cfv = self.__datetime_to_str(self.__tmp_cursor_value)
        self.__logger.info("Saved latest review timestamp to file: {}".format(cfv))
        return {self.cursor_field: cfv}

    @state.setter
    def state(self, value: Mapping[str, Any]):
        cfv = value.get(self.cursor_field)
        if cfv is not None:
            self.__logger.info("Read latest review timestamp from file: {}".format(cfv))
            self.__cursor_value = self.__str_to_datetime(cfv)
            self.__tmp_cursor_value = self.__str_to_datetime(cfv)

    def read_records(self, *args, **kwargs) -> Iterable[Mapping[str, Any]]:
        for record in super().read_records(*args, **kwargs):
            cfv = record.get(self.cursor_field)
            if cfv is not None:
                self.__tmp_cursor_value = max(self.__tmp_cursor_value, self.__str_to_datetime(cfv))
            yield record

    http_method = 'POST'

    raise_on_http_errors = False
    max_retries = 15
    retry_factor = 10.0

    def path(self, *, stream_state: Mapping[str, Any] = None, stream_slice: Mapping[str, Any] = None,
             next_page_token: Mapping[str, Any] = None, ) -> str:
        return "/_/PlayStoreUi/data/batchexecute"

    def request_params(self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None,
                       next_page_token: Mapping[str, Any] = None, ) -> MutableMapping[str, Any]:
        return {'hl': self.__languages[self.__language_ind], 'gl': 'US'}

    def request_headers(self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None,
                        next_page_token: Mapping[str, Any] = None) -> Mapping[str, Any]:
        return {'content-type': 'application/x-www-form-urlencoded'}

    def request_body_data(self, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None,
                          next_page_token: Mapping[str, Any] = None, ) -> Optional[Union[Mapping, str]]:
        app_id = self.__config['app_id']
        count = self.__config.get('max_reviews_per_request', 100)
        if (next_page_token is None) or isinstance(next_page_token, list):
            # noinspection PyProtectedMember
            res = GooglePlayFormats._Reviews.PAYLOAD_FORMAT_FOR_FIRST_PAGE.format(app_id=app_id, sort=GooglePlaySort.NEWEST, count=count,
                                                                                  score='null')
        else:
            # noinspection PyProtectedMember
            res = GooglePlayFormats._Reviews.PAYLOAD_FORMAT_FOR_PAGINATED_PAGE.format(app_id=app_id, sort=GooglePlaySort.NEWEST,
                                                                                      count=count, score='null',
                                                                                      pagination_token=next_page_token)
        return res

    @staticmethod
    def __fetch_reviews(response: requests.Response):
        dom = response.text
        match = json.loads(GooglePlayRegex.REVIEWS.findall(dom)[0])
        match = json.loads(match[0][2])
        return map(lambda rv: {k: spec.extract_content(rv) for k, spec in GooglePlayElementSpecs.Review.items()},
                   match[0] if len(match) > 0 else [])

    def parse_response(self, response: requests.Response, *, stream_state: Mapping[str, Any], stream_slice: Mapping[str, Any] = None,
                       next_page_token: Mapping[str, Any] = None, ) -> Iterable[Mapping]:
        result = []

        reviews = self.__fetch_reviews(response)
        for review in reviews:
            review[self.cursor_field] = self.__datetime_to_str(review[self.cursor_field])
            if review['repliedAt'] is not None:
                review['repliedAt'] = self.__datetime_to_str(review['repliedAt'])
            review['language'] = self.__languages[self.__language_ind]

            cfv = review.get(self.cursor_field)
            if (cfv is None) or (self.__str_to_datetime(cfv) > self.__cursor_value):
                result.append(review)

        self.__count_in_req = len(result)
        self.__count += self.__count_in_req

        return result

    @staticmethod
    def __fetch_next_page_token(response: requests.Response):
        dom = response.text
        match = json.loads(GooglePlayRegex.REVIEWS.findall(dom)[0])
        match = json.loads(match[0][2])
        return END_TOKEN if (len(match) == 0) or (len(match[-1]) == 0) else match[-1][-1]

    def next_page_token(self, response: requests.Response) -> Optional[Mapping[str, Any]]:
        timeout_ms = self.__config.get('timeout_milliseconds', 0)
        sleep(timeout_ms / 1000.0)

        token = self.__fetch_next_page_token(response)

        if (self.__count_in_req == 0) or isinstance(token, list):
            self.__logger.info("Fetched {} reviews for language=\"{}\"".format(self.__count, self.__languages[self.__language_ind]))

            self.__language_ind += 1

            self.__total_count += self.__count
            self.__count = 0

            token = END_TOKEN

            if self.__language_ind == len(self.__languages):
                self.__logger.info("Totally fetched {} reviews".format(self.__total_count))
                token = None

        return token


class SourceGooglePlayScraper(AbstractSource):
    @staticmethod
    def __transform_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
        if config['languages']['type'] == 'all':
            config = dict(deepcopy(config))
            config['languages']['type'] = 'selected'
            config['languages']['selected'] = ALL_LANGUAGES
        return config

    def check_connection(self, logger, config) -> Tuple[bool, any]:
        logger.info("Checking connection configuration...")

        logger.info("Checking \"app_id\"...")
        response = requests.get("https://play.google.com/store/apps/details", params={'id': config['app_id']})
        if not response.ok:
            error_text = "\"app_id\" \"{}\" is invalid!".format(config['app_id'])
            logger.error(error_text)
            return False, {'key': 'app_id', 'value': config['app_id'], 'error_text': error_text}
        logger.info("\"app_id\" is valid")

        logger.info("Connection configuration is valid")
        return True, None

    def streams(self, config: Mapping[str, Any]) -> List[Stream]:
        config = self.__transform_config(config)
        return [Reviews(config, authenticator=None)]
