# coding=utf-8

import sys
import platform
import time
import socket
import zlib
import threading
import json
import random
import itertools
from os import getenv
from collections import OrderedDict

import six
import requests
import pandas as pd

try:
    from urllib.parse import quote as urlquote
except ImportError:
    from urllib import quote as urlquote

from .utils import classproperty, isatty, suppress, get_mac_address
from .version import __version__ as current_version
from .exceptions import ResponseError


AUTH_API_URL = "https://dataapi.joinquant.com/v2/apis"  # 获取token


class QMDataClient(object):

    _threading_local = threading.local()
    _auth_params = {}

    _default_host = "127.0.0.1"
    _default_port = 7000

    request_timeout = 300
    request_attempt_count = 3

    enable_auth_prompt = True

    @classproperty
    def _local_socket_timeout(cls):
        """本地网络超时时间

        由于网络稍有延迟，将该时间设置为比服务器超时时间略长一点
        否则会有服务端正常处理完，而客户端已超时断开的问题
        """
        return cls.request_timeout + 5

    @staticmethod
    def _get_auth_param_from_env(name):
        for prefix in ["JQDATA", "JQDATASDK"]:
            value = getenv('_'.join([prefix, name]).upper())
            if value:
                return value

    @classmethod
    def _get_username_from_env(cls):
        for name in ["username", "user", "account", "mob"]:
            value = cls._get_auth_param_from_env(name)
            if value:
                return value

    @classmethod
    def _get_password_from_env(cls):
        for name in ["password", "passwd"]:
            value = cls._get_auth_param_from_env(name)
            if value:
                return value

    @classmethod
    def instance(cls, enable_env_param=True) -> "QMDataClient":
        _instance = getattr(cls._threading_local, '_instance', None)
        if _instance is None:
            if enable_env_param:
                if "username" not in cls._auth_params:
                    username = cls._get_username_from_env()
                    if username:
                        cls._auth_params["username"] = username
                if "password" not in cls._auth_params:
                    password = cls._get_password_from_env()
                    if password:
                        cls._auth_params["password"] = password
                if "host" not in cls._auth_params:
                    host = cls._get_auth_param_from_env("host")
                    if host:
                        cls._auth_params["host"] = host
                if "port" not in cls._auth_params:
                    port = cls._get_auth_param_from_env("port")
                    if port:
                        cls._auth_params["port"] = port
            if cls._auth_params:
                _instance = cls(**cls._auth_params)
            cls._threading_local._instance = _instance
        return _instance

    def __init__(self, host=None, port=None, username="", password="", token=""):
        self.host = host or self._default_host
        self.port = int(port or self._default_port)
        self.username = username
        self.password = password
        self.token = token

        assert self.host, "host is required"
        assert self.port, "port is required"
        assert self.username or self.token, "username is required"
        assert self.password or self.token, "password is required"

        self.client = None
        self.inited = False
        self.not_auth = True
        self.compress = True
        self.data_api_url = ""
        self._http_token = ""
        self._http_user_agent = ""

        self._request_id_generator = itertools.count(
            random.choice(range(0, 1000, 10))
        )

    @classmethod
    def set_request_params(cls, **params):
        for key, val in params.items():
            if "enable_auth_prompt" in params:
                cls.enable_auth_prompt = bool(val)
            elif key == "request_timeout":
                try:
                    request_timeout = float(val)
                    if request_timeout < 0:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError("请求超时时间需要为一个 >= 0 的数")
                cls.request_timeout = request_timeout
                try:
                    instance = cls.instance(enable_env_param=False)
                except Exception:
                    instance = None
                if instance and instance.inited and instance.client:
                    try:
                        try:
                            sock = instance.client._iprot.trans._trans.sock
                        except AttributeError:
                            sock = instance.client._iprot.trans.sock
                        sock.settimeout(cls.request_timeout)
                    except Exception:
                        pass
            elif key == "request_attempt_count":
                try:
                    request_attempt_count = int(val)
                    if request_attempt_count <= 0 or request_attempt_count > 10:
                        raise ValueError()
                except (TypeError, ValueError):
                    raise ValueError("请求尝试次数需要为一个 > 0 且 <= 10 的整数")
                cls.request_attempt_count = request_attempt_count
            elif key in (
                "request_username", "request_password",
                "request_host", "request_port",
            ):
                key = key.replace('request_', '')
                if val is None:
                    if key in cls._auth_params:
                        cls._auth_params.pop(key)
                else:
                    cls._auth_params[key] = val

    @classmethod
    def set_auth_params(cls, **params):
        try:
            instance = cls.instance(enable_env_param=False)
        except Exception:
            instance = None
        if params != cls._auth_params and instance:
            instance._reset()
            cls._threading_local._instance = None
        cls._auth_params.update(params)
        cls.instance().ensure_auth()

    def ensure_auth(self):
        if self.inited:
            return
        if not self.username and not self.token:
            raise RuntimeError("not inited")
        # 通过HTTP获取token
        if self.username and self.password:
            self.set_http_token()
            if not self._http_token:
                raise Exception("认证失败，请检查用户名和密码")
        elif self.token:
            self._http_token = self.token
        else:
            raise Exception("未提供认证信息")
        if self.enable_auth_prompt:
            print("auth success")
        self.not_auth = False
        self.inited = True

    def _reset(self):
        self.inited = False
        self.http_token = ""
        self._http_user_agent = ""

    def logout(self):
        self._reset()
        self._threading_local._instance = None
        self.__class__._auth_params = {}
        if self.enable_auth_prompt:
            print("已退出")

    def get_error(self, response):
        err = None
        if six.PY2:
            system = platform.system().lower()
            if system == "windows":
                err = Exception(response.error.encode("gbk"))
            else:
                err = Exception(response.error.encode("utf-8"))
        else:
            err = Exception(response.error)
        return err

    def query(self, method, params):
        params = params.copy() if params else {}
        params["method"] = method
        params["token"] = self.http_token
        resp = self.request_http(params)
        if resp is None:
            raise Exception("服务器无响应")
        try:
            result = resp.json()
        except Exception:
            raise Exception("服务器返回非JSON数据: {}".format(getattr(resp, 'text', '')))
        if not result.get("status", True):
            raise self.get_error(result)
        return result.get("msg", result)

    def _ping_server(self):
        if not self.client or not self.inited:
            return False
        for _ in range(self.request_attempt_count):
            try:
                msg = self.query("ping", {})
                break
            except ResponseError:
                msg = None
                continue
            except Exception:
                return False
        return msg == "pong"

    @classmethod
    def convert_message(cls, msg):
        if not isinstance(msg, dict):
            return msg

        data_type = msg.get("data_type", None)
        data_value = msg.get("data_value", None)
        if data_type is not None and data_value is not None:
            params = data_value
            if data_type.startswith("pandas"):
                data_index_type = params.pop("index_type", None)
                if data_index_type == "Index":
                    params["index"] = pd.Index(params["index"])
                elif data_index_type == "MultiIndex":
                    params["index"] = (
                        pd.MultiIndex.from_tuples(params["index"])
                        if len(params["index"]) > 0 else None
                    )
                if data_type == "pandas_dataframe":
                    dtypes = params.pop("dtypes", None)
                    data = params.get("data", None)
                    if isinstance(data, list):
                        index = params.get("index")
                        msg = pd.DataFrame(OrderedDict(data), index=index)
                    else:
                        msg = pd.DataFrame(**params)
                    if dtypes:
                        try:
                            msg = msg.astype(dtypes, copy=False)
                        except Exception:
                            for col, dtype in dtypes.items():
                                try:
                                    msg[col] = msg[col].astype(dtype)
                                except Exception:
                                    continue
                elif data_type == "pandas_series":
                    msg = pd.Series(**params)
                elif data_type == "pandas_panel":
                    # Panel已废弃，且thrift协议已移除，直接跳过
                    msg = None
        else:
            msg = {
                key: cls.convert_message(val)
                for key, val in msg.items()
            }
        return msg

    def __call__(self, method, **kwargs):
        err, result = None, None
        for attempt_index in range(self.request_attempt_count):
            try:
                result = self.query(method, kwargs)
                break
            except Exception as ex:
                err = ex
                if attempt_index < self.request_attempt_count - 1:
                    time.sleep(0.6)
        if result is None and isinstance(err, Exception):
            raise err
        return self.convert_message(result)

    def __getattr__(self, method):
        return lambda **kwargs: self(method, **kwargs)

    def test_network_speed(self, size=10000000, count=5):
        raise NotImplementedError("test_network_speed仅支持thrift协议，已被移除")

    def get_data_api_url(self):
        return self.data_api_url

    @property
    def http_token(self):
        if not self._http_token:
            self.set_http_token()
        return self._http_token

    @http_token.setter
    def http_token(self, value):
        self._http_token = value

    @http_token.deleter
    def http_token(self):
        self._http_token = ""

    def request_http(self, params):
        if not self._http_user_agent:
            self._http_user_agent = 'JQDataSDK/{}'.format(current_version)
            try:
                self._http_user_agent += " {}/{}".format(
                    platform.system(), platform.release()
                )
            except Exception:
                pass
            self._http_user_agent += " User/{}".format(self.username)

        headers = {'User-Agent': self._http_user_agent}
        for attempt_index in range(self.request_attempt_count):
            try:
                resp = requests.post(
                    AUTH_API_URL,
                    data=json.dumps(params),
                    headers=headers,
                    timeout=self.request_timeout
                )
                if resp.status_code == 200 or resp.text[:5] == 'error':
                    return resp
                elif resp.status_code == 429:
                    raise Exception("请求频率过高，请稍后再试")
                elif resp.status_code < 500:
                    raise Exception(resp.text[:100])
                else:
                    resp.raise_for_status()
            except requests.exceptions.RequestException as ex:
                if attempt_index < self.request_attempt_count - 1:
                    time.sleep(0.1)
                else:
                    raise

    def set_http_token(self):
        username, password = self.username, self.password
        if not username or not password:
            return
        params = {
            "method": "get_current_token",
            "mob": username,
            "pwd": urlquote(password),  # 给密码编码，防止使用特殊字符登录失败
        }
        try:
            resp = self.request_http(params)
            if resp is None:
                return
            text = getattr(resp, 'text', '')
            if text[:5] == 'error':
                raise Exception(text)
            self._http_token = text.strip()
        except Exception:
            pass
        return self._http_token

    def get_http_token(self):
        return self.http_token
