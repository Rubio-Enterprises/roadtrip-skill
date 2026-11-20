"""A stand-in for urllib's urlopen, the one place a tools/ client meets the
network. Everything on the near side of it runs for real."""

import json


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeNetwork:
    """`answers` maps a URL substring to a JSON payload, an exception to raise,
    or a function of the URL returning either. Every URL asked for is kept in
    `urls`; a URL with no answer fails like an unreachable host."""

    def __init__(self, answers):
        self.answers = answers
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        for needle, answer in self.answers.items():
            if needle in url:
                if callable(answer):
                    answer = answer(url)
                if isinstance(answer, Exception):
                    raise answer
                return _Response(answer)
        raise OSError("no fake answer for this URL")

    def hosts(self):
        return [u.split("/")[2] for u in self.urls]
