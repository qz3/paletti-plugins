#!/usr/bin/env python

""" Reference implementation """

import html
import json
import lxml.etree
import re
import time
import urllib
import urllib3
import urllib3.util

from urllib.parse import parse_qs

import paletti.utils

urllib3.disable_warnings()

GET_PARAMS = {'layout': 'mobile', 'ajax': '1'}
HOSTS = ['youtube.com', 'm.youtube.com', 'www.youtube.com']
MOBILE_HEADERS = {'User-Agent': 'Mozilla/5.0 (Linux; Android 7.0; PLUS Build/'
                  'NRD90M) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0'
                  '.3163.98 Mobile Safari/537.36',
                  'Accept-Encoding': 'gzip, deflate',
                  'Accept-Language': 'en'}
MAINHOST = 'https://m.youtube.com'
STREAM_TYPE = 'video/seperate' # video/seperate, video/combined, audio

http_mainhost = urllib3.HTTPSConnectionPool('m.youtube.com', headers=MOBILE_HEADERS)


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
    d['url'] = url
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
    if not stream_info:
        print('Error: couldnt get video streams.')
        return None
    for s in stream_info.split(','):
        stream = {}
        for parameter in s.split('&'):
            key, value = parameter.split('=')
            value = urllib.parse.unquote(value)
            stream[key] = value
        codec = stream['type'].split('codecs=')[1].strip('"')
        stream['codec'] = codec.split('.')[0]
        type_ = stream['type'].split(';')[0]
        stream['type'], stream['container'] = type_.split('/')
        if ',+' in codec:
            stream['type'] = 'audio+video'
        if 'quality_label' in stream:
            stream['quality'] = stream['quality_label']
        elif 'bitrate' in stream:
            stream['quality'] = stream['bitrate']
        try:
            stream['quality_int'] = int(''.join([x for x in stream['quality'] if x.isdigit()]))
        except ValueError:
            stream['quality_int'] = 0
        streams.append(stream)
    d['streams'] = streams
    return d


def get_subtitles(url, lang):
    parsed_url = urllib3.util.url.parse_url(url)
    query_data = re.split('[=&]', parsed_url.query)
    query = dict(zip(query_data[::2], query_data[1::2]))
    fields = {'lang': lang, 'v': query['v']}
    response = http_mainhost.request('GET', '/api/timedtext', fields=fields)
    if 'Content-Length' in response.headers:
        print('Subtitle not available')
        return None
    tree = lxml.etree.fromstring(response.data)
    elements = tree.xpath('//text')
    formatted = []
    for i, elem in enumerate(elements):
        formatted.append(str(i+1))
        s = elem.get('start')
        d = elem.get('dur')
        h_m_s = time.strftime('%H:%M:%S', time.gmtime(float(s)))
        start = f'{h_m_s},{float(s)%1*100:2.0f}'
        end_int = float(s) + float(d)
        h_m_s = time.strftime('%H:%M:%S', time.gmtime(end_int))
        end = f'{h_m_s},{end_int%1*100:3.0f}'.replace(' ', '0')
        formatted.append(f'{start} --> {end}')
        formatted.append(html.unescape(elem.text))
        formatted.append('')
    return '\n'.join(formatted)


def parse_userinput(raw):
    parsed = urllib3.util.parse_url(raw)
    if not parsed.scheme:
        return 'search_query'
    if parsed.path == '/playlist':
        return 'playlist'
    if parsed.path.startswith('/channel/'):
        return 'channel'
    if parsed.path.startswith('/user/'):
        return 'user'
    return None


def playlist(url, results=20):
    parsed_url = urllib3.util.url.parse_url(url)
    fields_ = GET_PARAMS.copy()
    query_data = re.split('[=&]', parsed_url.query)
    query = dict(zip(query_data[::2], query_data[1::2]))
    fields_.update(query)
    types, titles, urls, thumbs = [], [], [], []
    keys = ('type', 'title', 'url', 'thumbnail')

    while len(types) < results or results == 0:
        response = http_mainhost.request('GET', '/playlist', fields=fields_)
        html_source = response.data.decode('utf-8')
        source = html_source[4:].replace('\\U', '\\u')
        j = json.loads(source, strict=False)
        if 'ctoken' in fields_:
            result_content = j['content']['continuation_contents']['contents']
        else:
            result_content = j['content']['section_list']['contents'][0]['contents'][0]['contents']
        for element in result_content:
            type_ = 'video'
            types.append(type_.replace('compact_', ''))
            titles.append(element['title']['runs'][0]['text'])
            url = MAINHOST + '/watch?v=' + element['video_id']
            urls.append(url)
            thumbnail = 'https://i.ytimg.com/vi/' + element['video_id'] + '/mqdefault.jpg'
            thumbs.append(thumbnail)

        if 'ctoken' not in fields_:
            if not j['content']['section_list']['contents'][0]['contents'][0]['continuations']:
                break
            ctoken = j['content']['section_list']['contents'][0]['contents'][0]['continuations'][0]['continuation']
        else:
            if not j['content']['continuation_contents']['continuations']:
                break
            for c in j['content']['continuation_contents']['continuations']:
                if c['item_type'] == 'next_continuation_data':
                    ctoken = c['continuation']
        fields_['ctoken'] = ctoken
        fields_['action_continuation'] = '1'

    output_dict = [dict(zip(keys, x)) for x in zip(types, titles, urls, thumbs)]
    if results:
        return output_dict[:results]
    return output_dict


def search(query, results=20):
    """ Perform a search and return the result.

    :param query: the search query.
    :return: a list of dicts for the search result.
    """
    if not query.strip():
        return []
    fields_ = GET_PARAMS.copy()
    fields_['q'] = query
    types, titles, urls, thumbs = [], [], [], []
    keys = ('type', 'title', 'url', 'thumbnail')
    while len(types) < results:
        response = http_mainhost.request('GET', '/results', fields=fields_)
        html_source = response.data.decode('utf-8')
        source = html_source[4:].replace('\\U', '\\u')
        j = json.loads(source, strict=False)
        if 'ctoken' in fields_:
            result_content = j['content']['continuation_contents']['contents']
        else:
            result_content = j['content']['search_results']['contents']
        for element in result_content:
            type_ = (element['item_type'])
            if type_ in ['message', 'showing_results_for']:
                continue
            types.append(type_.replace('compact_', ''))
            titles.append(element['title']['runs'][0]['text'])
            if 'endpoint' in element:
                url = MAINHOST + element['endpoint']['url']
            elif 'navigation_endpoint' in element:
                url = MAINHOST + element['navigation_endpoint']['url']
            urls.append(url)
            thumbs.append(element['thumbnail_info']['url'])

        if 'ctoken' not in fields_:
            if not j['content']['search_results']['continuations']:
                break
            ctoken = j['content']['search_results']['continuations'][0]['continuation']
            del (fields_['q'])
        else:
            if not j['content']['continuation_contents']['continuations']:
                break
            for c in j['content']['continuation_contents']['continuations']:
                if c['item_type'] == 'next_continuation_data':
                    ctoken = c['continuation']
        fields_['ctoken'] = ctoken
        fields_['action_continuation'] = '1'

    return [dict(zip(keys, x)) for x in zip(types, titles, urls, thumbs)][:results]
