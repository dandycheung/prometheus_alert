import os, json, datetime, yaml, time
# from lib.Log import logger
from flask import Flask, request, render_template
from gevent.pywsgi import WSGIServer
from jinja2 import Environment, FileSystemLoader
from dateutil import parser
# python3.6
from http import HTTPStatus
from urllib.request import Request, urlopen
from urllib.parse import urlencode, quote_plus
from urllib.error import HTTPError
from settings import NOTICE_SETTINGS, HOST
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import ssl
except ImportError:
    ssl = None


def time_zone_conversion(utctime):
    format_time = parser.parse(utctime).strftime('%Y-%m-%dT%H:%M:%SZ')
    time_format = datetime.datetime.strptime(format_time, "%Y-%m-%dT%H:%M:%SZ")
    return str(time_format + datetime.timedelta(hours=8))


app = Flask(__name__)


class Sender:
    _address = None

    @staticmethod
    def request(url, method='GET', headers=None, params=None, data=None, files=False):
        """
        :param url:
        :param method:
        :param headers:
        :param params:
        :param data:
        :param files:
        :return:
        """

        # 发送地址链接拼接
        if url.startswith('/'):
            url = url.lstrip('/')
        full_url = "?".join([url, urlencode(params)]) if params else url
        try:
            if files:
                headers = {}
                headers.update({'Content-Type': 'application/zip'})
                data = data
            else:
                data = bytes(data, 'utf8')
            # 初始化请求参数
            req = Request(
                url=full_url, data=data,
                headers=headers, method=method,
            )
            ctx = ssl.SSLContext()
            return urlopen(req, timeout=10, context=ctx)
        except HTTPError as e:
            if e.code in [HTTPStatus.SERVICE_UNAVAILABLE, HTTPStatus.INTERNAL_SERVER_ERROR]:
                print("服务异常，请检查：{}".format(e.reason))
                return False
            else:
                print("严重异常，请检查：{}".format(e.reason))
                return False


class NoticeSender:
    _sender = None
    _sender_config = None
    _write_path = None
    _req = None

    def _get_sender_config(self):
        """
        :return:
        """
        try:
            NOTICE_SETTINGS
        except NameError:
            raise NameError("需要定义：NOTICE_SETTINGS")

        if isinstance(NOTICE_SETTINGS, dict):
            self._sender_config = [NOTICE_SETTINGS]
        elif isinstance(NOTICE_SETTINGS, list):
            self._sender_config = NOTICE_SETTINGS
        else:
            raise TypeError('告警通知配置文件错误，请检查！')
        self._check_notice_config()
        self._req = Sender()

    def _check_notice_config(self):
        """
        :return:
        """

        for config in self._sender_config:
            for key, value in config.items():
                if key not in ['token', 'secret', 'msg_type']:
                    raise KeyError('Error key in config dict!')
                if not value:
                    raise ValueError('Error value for key:{}!'.format(key))

    def dingtalk_sender(self, title, msg, settings: dict, mentioned=None, is_all=True):
        """
        :param title:
        :param msg:
        :param settings:
        :param mentioned:
        :param is_all:
        :return:
        """
        import time
        import base64
        import hmac
        import hashlib
        headers = {'Content-Type': 'application/json'}
        _url = "https://oapi.dingtalk.com/robot/send"
        params = {'access_token': settings['token']}
        if 'secret' in settings.keys():
            timestamp = int(round(time.time() * 1000))
            secret_enc = settings['secret'].encode('utf-8')
            string_to_sign = '{}\n{}'.format(timestamp, settings['secret'])
            string_to_sign_enc = string_to_sign.encode('utf-8')
            hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
            sign = quote_plus(base64.b64encode(hmac_code))
            params['timestamp'] = timestamp
            params['sign'] = sign
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": """## {}\n\n{}""".format(title, msg)
            }
        }
        if is_all or (not is_all and not mentioned):
            at = {
                "isAtAll": is_all
            }
        else:
            if not isinstance(mentioned, list):
                raise TypeError("消息接收人必须为列表!")
            at = {
                "atMobiles": mentioned,
                "isAtAll": is_all
            }
        data['at'] = at

        res = self._req.request(
            url=_url, params=params, data=json.dumps(data),
            headers=headers, method='POST'
        )
        result = json.loads(res.read().decode("UTF-8"))
        if result['errcode'] != 0:
            print("请求异常：{}".format(result['errmsg']))
            return False
        else:
            print("请求成功：{}".format(result['errmsg']))
            return True

    def wechat_sender(self, msg, settings: dict):
        """
        :param msg:
        :param settings:
        :return:
        """

        _url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        params = {'key': settings['token'], 'debug': 1}
        headers = {'Content-Type': 'application/json'}
        # data = {
        #     "msgtype": "template_card",
        #     "template_card": {
        #         "card_type": "news_notice",
        #         "source": {
        #             "icon_url": "https://wework.qpic.cn/wwpic/252813_jOfDHtcISzuodLa_1629280209/0",
        #             "desc": "监控告警",
        #             "desc_color": 0
        #         },
        #         "main_title": {
        #             "title": "正在使用新TSP监控告警",
        #             "desc": "正在使用新TSP监控告警"
        #         },
        #         "card_image": {
        #             "url": "https://wework.qpic.cn/wwpic/354393_4zpkKXd7SrGMvfg_1629280616/0",
        #             "aspect_ratio": 2.25
        #         },
        #         "image_text_area": {
        #             "type": 1,
        #             "url": "https://work.weixin.qq.com",
        #             "title": "正在使用新TSP监控告警",
        #             "desc": "正在使用新TSP监控告警",
        #             "image_url": "https://wework.qpic.cn/wwpic/354393_4zpkKXd7SrGMvfg_1629280616/0"
        #         },
        #         "quote_area": {
        #             "type": 1,
        #             "url": "https://work.weixin.qq.com/?from=openApi",
        #             "title": "引用文本标题",
        #             "quote_text": "Jack：告警~\nBalian：消息内容！"
        #         },
        #         "vertical_content_list": [
        #             {
        #                 "title": "消息内容",
        #                 "desc": "告警！"
        #             }
        #         ],
        #         "horizontal_content_list": [
        #             {
        #                 "keyname": "告警内容1",
        #                 "value": "提示1"
        #             },
        #             {
        #                 "keyname": "告警内容2",
        #                 "value": "提示2",
        #                 "type": 1,
        #                 "url": "https://work.weixin.qq.com/?from=openApi"
        #             },
        #         ],
        #         "jump_list": [
        #             {
        #                 "type": 1,
        #                 "url": "https://grafana.newtsp.newcowin.com",
        #                 "title": "grafana地址"
        #             }, {
        #                 "type": 1,
        #                 "url": "https://prometheus.newtsp.newcowin.com",
        #                 "title": "prometheus地址"
        #             }, {
        #                 "type": 1,
        #                 "url": "https://prometheus.newtsp.newcowin.com",
        #                 "title": "告警内容展示地址"
        #             }
        #
        #         ],
        #         "card_action": {
        #             "type": 1,
        #             "url": "https://grafana.newtsp.newcowin.com"
        #         }
        #     }
        # }
        res = self._req.request(
            url=_url, params=params, data=json.dumps(msg, ensure_ascii=False), headers=headers, method='POST'
        )
        result = json.loads(res.read().decode("UTF-8"))
        if result['errcode'] != 0:
            print("请求异常：{}".format(result['errmsg']))
            return False
        else:
            print("请求成功：{}".format(result['errmsg']))
            return True

    def create_temp(self, message: str):
        import time

        if not self._write_path:
            self._write_path = './'
        else:
            if not os.path.exists(self._write_path):
                os.makedirs(self._write_path)
        current_files = os.path.join(self._write_path, "{}.txt".format(time.time()))
        try:
            with open(current_files, 'wb') as fff:
                fff.write(str(message).encode('ascii') + b"\n")
            return current_files
        except Exception as error:
            print("创建文件失败:{},{}".format(current_files, error))
            return False

    @staticmethod
    def get_wechat_media(media_file, settings: dict):
        import requests
        _upload_media_url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media'
        if not os.path.exists(media_file):
            raise Exception("文件不��在:{}".format(media_file))
        params = {'key': settings['token'], 'type': 'file', 'debug': 1}
        with open(media_file, 'r') as fff:
            try:
                res = requests.post(
                    url="?".join([_upload_media_url, urlencode(params)]) if params else _upload_media_url,
                    files={'file': fff}
                )
            except Exception as error:
                print("读取临时文件失败:{}".format(error))
            return res.json()

    def wechat_file_sender(self, msg: str, settings: dict, mentioned=None, is_all=False):
        if is_all:
            mentioned = ["@all"]
        elif mentioned and not is_all:
            mentioned = mentioned
        else:
            mentioned = []
        _url = 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send'
        params = {'key': settings['token'], 'type': 'file'}
        headers = {'Content-Type': 'application/json'}
        media_file = self.create_temp(message=msg)
        if not media_file:
            return False

        res = self.get_wechat_media(media_file=media_file, settings=settings)
        data = {
            "msgtype": "file",
            "file": {
                "media_id": res['media_id'],
                "mentioned_mobile_list": mentioned
            }
        }
        res = self._req.request(
            url=_url, method='POST', headers=headers,
            params=params, data=json.dumps(data)
        )
        os.remove(media_file)
        return res

    def dingtalk_file_sender(self):
        pass

    def sender(self, title, msg, mentioned, is_all=False):
        """
        :param title:
        :param msg:
        :param mentioned:
        :param is_all:
        :return:
        """
        thead_list = list()
        self._get_sender_config()
        for setting in self._sender_config:
            with ThreadPoolExecutor(max_workers=3) as worker:
                args = (title, msg, setting, mentioned, is_all)
                if setting['msg_type'] == 'WECHAT_ROBOT':
                    res = worker.submit(self.wechat_sender, *args)
                elif setting['msg_type'] == 'DINGTALK_ROBOT':
                    res = worker.submit(self.dingtalk_sender, *args)
                else:
                    raise Exception('发送类型错误！')
                thead_list.append(res)

        for competed in as_completed(thead_list, timeout=10):
            print(competed.result())

    def sender_file(self, title, msg, mentioned, is_all=False):
        """
        :param title:
        :param msg:
        :param mentioned:
        :param is_all:
        :return:
        """
        thead_list = list()
        self._get_sender_config()
        for setting in self._sender_config:
            with ThreadPoolExecutor(max_workers=3) as worker:
                args = (msg, setting)
                if setting['msg_type'] == 'WECHAT_ROBOT':
                    res = worker.submit(self.wechat_file_sender, *args[1:])
                elif setting['msg_type'] == 'DINGTALK_ROBOT':
                    res = worker.submit(self.dingtalk_sender, *args)
                else:
                    raise Exception('发送类型错误！')
                thead_list.append(res)

        for competed in as_completed(thead_list, timeout=10):
            print(competed.result())


class ParseingTemplate:
    def __init__(self, templatefile):
        self.templatefile = templatefile

    def template(self, **kwargs):
        try:
            env = Environment(loader=FileSystemLoader('templates'))
            template = env.get_template(self.templatefile)
            template_content = template.render(kwargs)
            return template_content
        except Exception as error:
            raise error


def write_html_file(filename, content):
    """
    :param filename:
    :param content:
    :return:
    """
    try:
        with open(filename, 'w', encoding='utf-8') as fff:
            fff.write(content)
    except Exception as error:
        print("写入文件失败：{},原因:".format(filename, error))


def get_email_conf(file, email_name=None, action=0):
    """
    :param file: yaml格式的文件类型
    :param email_name: 发送的邮件列表名
    :param action: 操作类型，0: 查询收件人的邮件地址列表, 1: 查询收件人的列表名称, 2: 获取邮件账号信息
    :return: 根据action的值，返回不通的数据结构
    """
    try:
        with open(file, 'r', encoding='utf-8') as fr:
            read_conf = yaml.safe_load(fr)
            if action == 0:
                for email in read_conf['email']:
                    if email['name'] == email_name:
                        return email['receive_addr']
                    else:
                        print("%s does not match for %s" % (email_name, file))
                else:
                    print("No recipient address configured")
            elif action == 1:
                return [items['name'] for items in read_conf['email']]
            elif action == 2:
                return read_conf['send']
    except KeyError:
        print("%s not exist" % email_name)
        exit(-1)
    except FileNotFoundError:
        print("%s file not found" % file)
        exit(-2)
    except Exception as e:
        raise e


@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        n = NoticeSender()
        prometheus_data = json.loads(request.data)
        # 时间转换，转换成东八区时间
        for k, v in prometheus_data.items():
            if k == 'alerts':
                for items in v:
                    if items['status'] == 'firing':
                        items['startsAt'] = time_zone_conversion(items['startsAt'])
                    else:
                        items['startsAt'] = time_zone_conversion(items['startsAt'])
                        items['endsAt'] = time_zone_conversion(items['endsAt'])
        # team_name = prometheus_data["commonLabels"]["team"]
        team_name = "wechat_webhook"
        generate_html_template_subj = ParseingTemplate('html_template_firing.html')
        html_template_content = generate_html_template_subj.template(
            prometheus_monitor_info=prometheus_data
        )
        filename = os.path.join('templates', "{}.html".format(int(time.time())))
        url = os.path.join('show', "{}.html".format(int(time.time())))
        full_url = os.path.join(HOST, url)
        write_html_file(filename=filename, content=html_template_content)
        data = {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "news_notice",
                "source": {
                    "icon_url": "https://www.kaiyihome.com/favicon.ico",
                    "desc": "监控告警",
                    "desc_color": 0
                },
                "main_title": {
                    "title": "正在使用新TSP监控告警",
                    "desc": "正在使用新TSP监控告警"
                },
                "card_image": {
                    "url": "https://prometheus.io/assets/prometheus_logo_grey.svg",
                    "aspect_ratio": 2.25
                },
                "quote_area": {
                    "type": 1,
                    "url": "https://work.weixin.qq.com/?from=openApi",
                    "title": "引用文本标题",
                    "quote_text": "Jack：告警~\nBalian：消息内容！"
                },
                "vertical_content_list": [
                    {
                        "title": "消息内容",
                        "desc": "告警！"
                    }
                ],
                "horizontal_content_list": [
                    {
                        "keyname": "告警内容1",
                        "value": "提示1"
                    },
                    {
                        "keyname": "告警内容2",
                        "value": "提示2",
                        "type": 1,
                        "url": "https://work.weixin.qq.com/?from=openApi"
                    },
                ],
                "jump_list": [
                    {
                        "type": 1,
                        "url": "https://grafana.newtsp.newcowin.com",
                        "title": "grafana地址"
                    }, {
                        "type": 1,
                        "url": "https://prometheus.newtsp.newcowin.com",
                        "title": "prometheus地址"
                    }, {
                        "type": 1,
                        "url": full_url,
                        "title": "告警内容展示地址"
                    }

                ],
                "card_action": {
                    "type": 1,
                    "url": "https://grafana.newtsp.newcowin.com"
                }
            }
        }
        # 获取收件人邮件列表
        # email_list = get_email_conf('email.yaml', email_name=team_name, action=0)
        n.sender(title="新TSP生产环境告警", msg=data)
        return "prometheus monitor"
    except Exception as e:
        raise e


@app.route("/show/<pages>")
def direct_show(pages):
    return render_template("{}.html".format(pages))


if __name__ == '__main__':
    WSGIServer(('0.0.0.0', 5000), app).serve_forever()
