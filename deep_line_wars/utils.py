from ctypes import cdll, byref, create_string_buffer
import json
from collections import namedtuple
import collections


def set_thread_name(str_name):
    name = str.encode(str_name)
    libc = cdll.LoadLibrary('libc.so.6')
    buff = create_string_buffer(len(str_name) + 1)
    buff.value = name
    libc.prctl(15, byref(buff), 0, 0, 0)


def load_json(file_path):
    return json.load(open(file_path, "rb"))


def update(d, u):
    for k, v in u.items():
        if isinstance(v, collections.Mapping):
            d[k] = update(d.get(k, {}), v)
        else:
            d[k] = v
    return d


def dict_to_object(d):
    for key, value in d.items():
        if isinstance(value, dict):
            d[key] = dict_to_object(value)
    return namedtuple('X', d.keys())(**d)