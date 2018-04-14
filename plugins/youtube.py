#!/usr/bin/env python

""" Reference implementation """

import json
import re
import time
import urllib
import urllib3
from urllib.parse import parse_qs

import paletti.utils

urllib3.disable_warnings()

GET_PARAMS = {'layout': 'mobile', 'ajax': '1'}
MOBILE_HEADERS = {'User-Agent': 'Mozilla/5.0 (Linux; Android 7.0; PLUS Build/'
                  'NRD90M) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0'
                  '.3163.98 Mobile Safari/537.36',
                  'Accept-Encoding': 'gzip, deflate',
                  'Accept-Language': 'en'}
MAINHOST = 'm.youtube.com'

http_mainhost = urllib3.HTTPSConnectionPool(MAINHOST, headers=MOBILE_HEADERS)


def download(url, path):
    """ Download a file and return an instance providing status information.

    :param url: the url of the file.
    :param path: the local filepath.
    :return: a `Download` instance.
    """
    dash_params = {'key': 'range', 'format': '-'}
    dl = paletti.utils.Downloader(url, path, dash_params)
    dl.start()
    return dl


def get_deep(dict_, *keys):
    for key in keys:
        try:
            dict_ = dict_[key]
        except KeyError:
            return None
    return dict_


def get_metadata(url):
    """ Extract the metadata for a video.

    :param url: the url.
    :return: a dictionary holding the metadata
    """
    d = {}
    parsed_url = urllib3.util.url.parse_url(url)
    fields_ = GET_PARAMS
    query_data = re.split('[=&]', parsed_url.query)
    query = dict(zip(query_data[::2], query_data[1::2]))
    fields_.update(query)
    response = http_mainhost.request('GET', '/watch', fields=fields_)
    response = response.data.decode('utf-8')[4:].replace('\\U', '\\u')
    j = json.loads(response, strict=False)

    vmc = get_deep(j, 'content', 'video_main_content', 'contents')[0]
    swf = get_deep(j, 'content', 'swfcfg', 'args')

    d['duration'] = get_deep(j, 'content', 'video', 'length_seconds')
    d['title'] = get_deep(j, 'content', 'video', 'title')

    d['likes'] = get_deep(vmc, 'like_button', 'like_count')
    d['dislikes'] = get_deep(vmc, 'like_button', 'dislike_count')
    desc = []
    for chunk in get_deep(vmc, 'description', 'runs'):
        desc.append(chunk['text'])
    d['desc'] = ''.join(desc)

    d['author'] = get_deep(swf, 'author')
    d['view_count'] = int(get_deep(swf, 'view_count'))
    d['thumbnail_small'] = get_deep(swf, 'iurlsd')
    d['thumbnail_big'] = get_deep(swf, 'iurl')
    d['avg_rating'] = float(get_deep(swf, 'avg_rating'))
    streams = []
    stream_info = get_deep(swf, 'adaptive_fmts')
    if not stream_info:
        # This is necessary for videos which have only one format
        stream_info = get_deep(swf, 'url_encoded_fmt_stream_map')
    for s in stream_info.split(','):
        stream = {}
        for parameter in s.split('&'):
            key, value = parameter.split('=')
            value = urllib.parse.unquote(value)
            stream[key] = value
        type_ = stream['type'].split(';')[0]
        stream['type'], stream['container'] = type_.split('/')
        streams.append(stream)
    d['streams'] = streams
    # FIXME: this doesn't work. Get date elsewhere.
    timestamp = streams[0]['lmt']
    timestamp = int(str(timestamp)[:10])
    d['upload_date'] = time.strftime('%Y-%m-%d', time.gmtime(timestamp))

    return d


def search(query):
    """ Perform a search and return the result.

    :param query: the search query.
    :return: a list of dicts for the search result.
    """
    fields_ = GET_PARAMS
    fields_['q'] = query
    response = http_mainhost.request('GET', '/results', fields=fields_)
    html_source = response.data.decode('utf-8')
    source = html_source[4:].replace('\\U', '\\u')
    j = json.loads(source, strict=False)
    ids, titles, urls, thumbs, fails = [], [], [], [], []
    keys = ('url', 'title', 'thumbnail')
    for element in j['content']['search_results']['contents']:
        try:
            ids.append(element['encrypted_id'])
            titles.append(element['title']['runs'][0]['text'])
            url = MAINHOST + element['endpoint']['url']
            urls.append(url)
            thumbs.append(element['thumbnail_info']['url'])
        except KeyError:
            print(f'KeyError: couldnt deal with {element}')
    return [dict(zip(keys, x)) for x in zip(urls, titles, thumbs)]
